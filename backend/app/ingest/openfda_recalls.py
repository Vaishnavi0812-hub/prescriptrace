"""openFDA drug enforcement reports (US recalls). Licence: CC0 / public domain."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import (
    RAW_DIR,
    DatasetInfo,
    IngestError,
    chunks,
    download,
    ingest_run,
    sha256,
    upsert_dataset,
)
from app.ingest.resolve import IngredientResolver
from app.models import Ingredient, Recall, RecallLink

log = logging.getLogger("ingest.recalls")

URL = "https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip"
INFO = DatasetInfo(
    code="openfda_enforcement",
    name="openFDA drug enforcement reports (FDA recalls)",
    source_url="https://open.fda.gov/apis/drug/enforcement/",
    licence="CC0 1.0 / public domain (openFDA)",
    licence_url="https://open.fda.gov/license/",
    region="US",
    limitations="US market recalls. Most products are not sold in India, so matches are usually "
    "'same ingredient, different product'. Records without structured openFDA fields are "
    "matched by ingredient name in the product description (lower confidence).",
)

# Ingredient names this short (or generic words) cause false matches inside free text.
MIN_NAME_LEN_FOR_TEXT_MATCH = 6
TEXT_MATCH_STOPLIST = {"water", "sodium", "oxygen", "alcohol", "glucose", "dextrose", "sucrose"}


def record_url(recall_number: str) -> str:
    query = urllib.parse.quote(f'recall_number:"{recall_number}"')
    return f"https://api.fda.gov/drug/enforcement.json?search={query}"


def parse_date(value: str | None) -> date | None:
    if not value or len(value) != 8:
        return None
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC).date()


def load_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json")]
        if len(names) != 1:
            raise IngestError(f"Expected one JSON file in {path.name}, found {names}")
        payload = json.loads(zf.read(names[0]))
    results = payload.get("results")
    if not isinstance(results, list):
        raise IngestError("openFDA enforcement file has no 'results' list (format changed?)")
    last_updated = payload.get("meta", {}).get("last_updated", "")
    return results, last_updated


class TextMatcher:
    """Whole-word ingredient-name matcher for free-text product descriptions."""

    def __init__(self, ingredients: dict[str, str]) -> None:
        usable = {
            n: rx
            for n, rx in ingredients.items()
            if len(n) >= MIN_NAME_LEN_FOR_TEXT_MATCH and n not in TEXT_MATCH_STOPLIST
        }
        # Longest names first so "insulin glargine" wins over "insulin".
        ordered = sorted(usable, key=len, reverse=True)
        self._lookup = usable
        self._pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in ordered) + r")\b")

    def find(self, text: str) -> set[str]:
        return {self._lookup[m] for m in self._pattern.findall(norm(text))}


def run(session: Session, refresh: bool = False) -> None:
    path = download(URL, RAW_DIR / "openfda" / "enforcement" / Path(URL).name, refresh=refresh)
    records, last_updated = load_records(path)
    dataset = upsert_dataset(
        session,
        INFO,
        version=last_updated or None,
        downloaded_at=datetime.now(UTC),
        sha256=sha256(path),
    )
    with ingest_run(session, dataset) as stats:
        stats.rows_in = len(records)
        drug_records = [r for r in records if r.get("product_type") == "Drugs"]
        stats.note(f"Records: {len(records)}, product_type=Drugs: {len(drug_records)}")

        resolver = IngredientResolver(session)
        known = {n: r for n, r in session.execute(select(Ingredient.name_norm, Ingredient.rxcui))}
        text_matcher = TextMatcher(known)

        session.execute(delete(Recall).where(Recall.dataset_id == dataset.id))
        recall_rows: list[dict[str, Any]] = []
        links_by_number: dict[str, list[dict[str, Any]]] = {}
        basis_counts = {"substance": 0, "text": 0, "none": 0}
        seen: set[str] = set()

        for rec in drug_records:
            number = rec.get("recall_number")
            if not number or number in seen:
                stats.rows_rejected += 1
                continue
            seen.add(number)
            recall_rows.append(
                {
                    "region": "US",
                    "source_record_id": number,
                    "classification": rec.get("classification"),
                    "reason": rec.get("reason_for_recall"),
                    "firm": rec.get("recalling_firm"),
                    "status": rec.get("status"),
                    "report_date": parse_date(rec.get("report_date")),
                    "product_description": rec.get("product_description"),
                    "lot_info": rec.get("code_info"),
                    "dataset_id": dataset.id,
                    "source_url": record_url(number),
                }
            )
            links_by_number[number] = _links(rec, resolver, text_matcher, basis_counts)

        stats.note(f"Ingredients added from RxNav: {resolver.flush_new_ingredients()}")
        id_by_number: dict[str, int] = {}
        for batch in chunks(recall_rows):
            ids = session.scalars(insert(Recall).returning(Recall.id), list(batch)).all()
            for row, new_id in zip(batch, ids, strict=True):
                id_by_number[row["source_record_id"]] = new_id

        link_rows = [
            {**link, "recall_id": id_by_number[number]}
            for number, links in links_by_number.items()
            for link in links
        ]
        for batch in chunks(link_rows):
            session.execute(insert(RecallLink), list(batch))

        stats.rows_out = len(recall_rows)
        stats.note(f"Recall links: {len(link_rows)}; records by match basis: {basis_counts}")


def _links(
    rec: dict[str, Any],
    resolver: IngredientResolver,
    text_matcher: TextMatcher,
    basis_counts: dict[str, int],
) -> list[dict[str, Any]]:
    ofda = rec.get("openfda") or {}
    brands = ofda.get("brand_name") or [None]
    links: list[dict[str, Any]] = []
    for product_rxcui in ofda.get("rxcui") or []:
        links.append(
            {
                "ingredient_rxcui": None,
                "product_rxcui": product_rxcui,
                "brand_text": brands[0],
                "match_basis": "rxcui",
            }
        )
    ingredient_ids: set[str] = set()
    for substance in ofda.get("substance_name") or []:
        resolved = resolver.resolve(substance)
        if resolved is not None:
            ingredient_ids.add(resolved.rxcui)
    basis = "substance" if ingredient_ids else "text"
    if not ingredient_ids:
        ingredient_ids = text_matcher.find(rec.get("product_description") or "")
    if not ingredient_ids:
        basis_counts["none"] += 1
    else:
        basis_counts[basis] += 1
    for rxcui in sorted(ingredient_ids):
        links.append(
            {
                "ingredient_rxcui": rxcui,
                "product_rxcui": None,
                "brand_text": brands[0],
                "match_basis": basis,
            }
        )
    return links
