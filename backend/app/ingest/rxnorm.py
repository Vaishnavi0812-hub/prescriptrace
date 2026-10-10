"""RxNorm Current Prescribable Content: the local drug vocabulary.

Public domain, no UMLS licence needed (SAB=RXNORM and MTHSPL only). Relationship rows
`RXCUI1|…|RXCUI2|…|RELA` read as "RXCUI2 RELA RXCUI1", e.g. (amoxicillin, tradename_of,
Augmentin) = "Augmentin is a tradename of amoxicillin" (verified against the 2026-09 release).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import (
    RAW_DIR,
    DatasetInfo,
    IngestError,
    download,
    ingest_run,
    replace_rows,
    sha256,
    upsert_dataset,
    upsert_rows,
)
from app.models import Brand, BrandIngredient, DrugName, Ingredient, Product, ProductIngredient

log = logging.getLogger("ingest.rxnorm")

URL = "https://download.nlm.nih.gov/rxnorm/RxNorm_full_prescribe_current.zip"
INFO = DatasetInfo(
    code="rxnorm_prescribe",
    name="RxNorm Current Prescribable Content",
    source_url="https://www.nlm.nih.gov/research/umls/rxnorm/docs/prescribe.html",
    licence="Public domain (no licence required, per NLM)",
    licence_url="https://www.nlm.nih.gov/research/umls/rxnorm/docs/prescribe.html",
    region="US",
    limitations="Approximates drugs currently prescribable in the US. Indian brand names are "
    "largely absent (handled by the curated India brand table).",
)

PRODUCT_TTYS = ("SCD", "SBD", "GPCK", "BPCK")
NAME_TTYS = ("IN", "PIN", "MIN", "BN", "DF", "SCDC", *PRODUCT_TTYS)
# Strength at the end of an SCDC name: "amoxicillin 500 MG", "insulin glargine 100 UNT/ML".
_STRENGTH = re.compile(r"\s(\d+(?:\.\d+)?)\s(\S+)$")


def _rrf(zf: zipfile.ZipFile, name: str) -> Iterator[list[str]]:
    matches = [n for n in zf.namelist() if n.endswith(f"/{name}") or n == name]
    if not matches:
        raise IngestError(f"{name} missing from RxNorm archive (format changed?)")
    with zf.open(matches[0]) as fh:
        for line in io.TextIOWrapper(fh, "utf-8"):
            yield line.rstrip("\n").split("|")


def parse_strength(scdc_name: str) -> tuple[float | None, str | None]:
    match = _STRENGTH.search(scdc_name)
    if not match:
        return None, None
    return float(match.group(1)), match.group(2)


class RxNormRelease:
    """Parsed view of the release, independent of the database (unit-testable)."""

    def __init__(self, path: Path) -> None:
        self.tty: dict[str, set[str]] = defaultdict(set)
        self.name: dict[str, str] = {}
        self.synonyms: dict[str, set[str]] = defaultdict(set)
        rel: dict[str, list[tuple[str, str]]] = defaultdict(list)
        with zipfile.ZipFile(path) as zf:
            for c in _rrf(zf, "RXNCONSO.RRF"):
                rxcui, sab, tty, text, suppress = c[0], c[11], c[12], c[14], c[16]
                if sab != "RXNORM" or suppress in ("O", "E"):
                    continue
                self.tty[rxcui].add(tty)
                if tty in NAME_TTYS:
                    self.name.setdefault(rxcui, text)
                elif tty in ("SY", "TMSY", "PSN"):
                    self.synonyms[rxcui].add(text)
            # Only keep relationships we use, keyed by RELA, as (subject, object) =
            # (RXCUI2, RXCUI1) so that "subject RELA object" reads naturally.
            wanted = {
                "tradename_of",
                "has_ingredient",
                "consists_of",
                "has_dose_form",
                "form_of",
                "contains",
            }
            for c in _rrf(zf, "RXNREL.RRF"):
                rela = c[7]
                if rela in wanted and c[2] == "CUI" and c[6] == "CUI":
                    rel[rela].append((c[4], c[0]))
        self.rel = rel
        if not self.of_type("IN"):
            raise IngestError("No ingredients (TTY=IN) found in RxNorm release")

    def of_type(self, tty: str) -> list[str]:
        return [rx for rx, ttys in self.tty.items() if tty in ttys]

    def pairs(self, rela: str, subj: str, obj: str) -> Iterator[tuple[str, str]]:
        """(subject, object) for "subject RELA object" restricted by TTY."""
        for s, o in self.rel[rela]:
            if subj in self.tty.get(s, ()) and obj in self.tty.get(o, ()):
                yield s, o

    def product_ingredients(self) -> dict[str, dict[str, tuple[float | None, str | None]]]:
        """product rxcui → {ingredient rxcui: (strength value, unit)}."""
        scdc_ing = dict(self.pairs("has_ingredient", "SCDC", "IN"))
        out: dict[str, dict[str, tuple[float | None, str | None]]] = defaultdict(dict)
        for product_tty in ("SCD", "SBD"):  # "SCD consists_of SCDC"
            for product, scdc in self.pairs("consists_of", product_tty, "SCDC"):
                self._add(out, product, scdc, scdc_ing)
        for pack_tty in ("GPCK", "BPCK"):
            for member_tty in ("SCD", "SBD"):
                for pack, member in self.pairs("contains", pack_tty, member_tty):
                    for ing, strength in out.get(member, {}).items():
                        out[pack].setdefault(ing, strength)
        return out

    def _add(
        self,
        out: dict[str, dict[str, tuple[float | None, str | None]]],
        product: str,
        scdc: str,
        scdc_ing: dict[str, str],
    ) -> None:
        ing = scdc_ing.get(scdc)
        if ing is not None:
            out[product][ing] = parse_strength(self.name.get(scdc, ""))


def run(session: Session, refresh: bool = False) -> None:
    path = download(URL, RAW_DIR / "rxnorm" / Path(URL).name, refresh=refresh)
    log.info("parsing %s", path.name)
    rx = RxNormRelease(path)
    version = _release_version(path)
    dataset = upsert_dataset(
        session, INFO, version=version, downloaded_at=datetime.now(UTC), sha256=sha256(path)
    )
    with ingest_run(session, dataset) as stats:
        ds = dataset.id
        ingredients: list[dict[str, Any]] = [
            {"rxcui": r, "name": rx.name[r], "name_norm": norm(rx.name[r]), "dataset_id": ds}
            for r in rx.of_type("IN")
        ]
        upsert_rows(session, Ingredient.__table__, ingredients, ["rxcui"])  # type: ignore[arg-type]
        ing_ids: set[str] = {i["rxcui"] for i in ingredients}

        dose_form = {p: rx.name.get(df) for p, df in _subject_object(rx, "has_dose_form")}
        brand_of_sbd = dict(rx.pairs("has_ingredient", "SBD", "BN"))
        products: list[dict[str, Any]] = []
        for tty in PRODUCT_TTYS:
            for r in rx.of_type(tty):
                brand = brand_of_sbd.get(r)
                products.append(
                    {
                        "rxcui": r,
                        "name": rx.name[r],
                        "tty": tty,
                        "dose_form": dose_form.get(r),
                        "brand_name": rx.name.get(brand) if brand else None,
                        "dataset_id": ds,
                    }
                )
        upsert_rows(session, Product.__table__, products, ["rxcui"])  # type: ignore[arg-type]

        product_ids: set[str] = {p["rxcui"] for p in products}
        session.execute(
            delete(ProductIngredient).where(ProductIngredient.product_rxcui.in_(product_ids))
        )
        pi_rows: list[dict[str, Any]] = [
            {
                "product_rxcui": prod,
                "ingredient_rxcui": ing,
                "strength_value": value,
                "strength_unit": unit,
            }
            for prod, ings in rx.product_ingredients().items()
            if prod in product_ids
            for ing, (value, unit) in ings.items()
            if ing in ing_ids
        ]
        for start in range(0, len(pi_rows), 5000):
            session.execute(insert(ProductIngredient), pi_rows[start : start + 5000])

        brands: list[dict[str, Any]] = [
            {"rxcui": b, "name": rx.name[b], "dataset_id": ds} for b in rx.of_type("BN")
        ]
        session.execute(delete(DrugName).where(DrugName.dataset_id == ds))
        upsert_rows(session, Brand.__table__, brands, ["rxcui"])  # type: ignore[arg-type]
        brand_ids: set[str] = {b["rxcui"] for b in brands}
        session.execute(delete(BrandIngredient).where(BrandIngredient.brand_rxcui.in_(brand_ids)))
        bi_rows = [
            {"brand_rxcui": b, "ingredient_rxcui": i}
            for b, i in set(rx.pairs("tradename_of", "BN", "IN"))
            if b in brand_ids and i in ing_ids
        ]
        session.execute(insert(BrandIngredient), bi_rows)

        names = _drug_names(rx, ds, ing_ids, brand_ids, product_ids)
        replace_rows(session, DrugName.__table__, ds, names)  # type: ignore[arg-type]

        stats.rows_in = len(rx.tty)
        stats.rows_out = len(ingredients) + len(products) + len(brands)
        stats.note(
            f"ingredients={len(ingredients)} products={len(products)} brands={len(brands)} "
            f"product_ingredient={len(pi_rows)} brand_ingredient={len(bi_rows)} "
            f"drug_names={len(names)}"
        )


def _subject_object(rx: RxNormRelease, rela: str) -> Iterator[tuple[str, str]]:
    yield from rx.rel[rela]


def _drug_names(
    rx: RxNormRelease, ds: int, ing_ids: set[str], brand_ids: set[str], product_ids: set[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(text: str, kind: str, **target: str | None) -> None:
        key = (norm(text), kind, next((v for v in target.values() if v), "") or "")
        if not key[0] or key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "text": text[:300],
                "text_norm": key[0][:300],
                "kind": kind,
                "ingredient_rxcui": target.get("ingredient_rxcui"),
                "product_rxcui": target.get("product_rxcui"),
                "brand_rxcui": target.get("brand_rxcui"),
                "india_brand_id": None,
                "country": "US",
                "dataset_id": ds,
                "source_ref": f"RXCUI:{next(v for v in target.values() if v)}",
            }
        )

    for r in ing_ids:
        add(rx.name[r], "ingredient", ingredient_rxcui=r)
    for pin, ing in rx.pairs("form_of", "PIN", "IN"):  # salts: "metformin hydrochloride"
        if ing in ing_ids:
            add(rx.name[pin], "synonym", ingredient_rxcui=ing)
    for b in brand_ids:
        add(rx.name[b], "brand", brand_rxcui=b)
    for p in product_ids:
        add(rx.name[p], "product", product_rxcui=p)
        for syn in rx.synonyms.get(p, ()):  # e.g. "Augmentin 875 MG / 125 MG Oral Tablet"
            add(syn, "product", product_rxcui=p)
    return rows


def _release_version(path: Path) -> str | None:
    with zipfile.ZipFile(path) as zf:
        readmes = [n for n in zf.namelist() if n.lower().startswith("readme")]
        for name in readmes:
            text = zf.read(name).decode("utf-8", "ignore")
            match = re.search(r"Release\s+(\w+ ?\d{1,2},? \d{4}|\d{8})", text)
            if match:
                return match.group(1)
        dates = [i.date_time for i in zf.infolist()]
    newest = max(dates)
    return f"{newest[0]:04d}-{newest[1]:02d}-{newest[2]:02d}"
