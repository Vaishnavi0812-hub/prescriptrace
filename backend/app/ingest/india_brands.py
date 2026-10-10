"""Curated Indian brand → ingredient table.

Two steps, so a person can always see why a row exists:
  1. `python -m app.ingest.india_brands verify` fetches every source_url in
     data/curated/india_brands.csv, confirms each required term appears on the page, saves the
     composition text found (quote) and the date to india_brands_verified.csv (committed).
  2. `python -m app.ingest india_brands` loads only verified rows whose ingredients ALL map to
     RxNorm. A combination with an unmapped ingredient could hide an interaction, so it is
     rejected (and reported), never loaded partially.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import DatasetInfo, IngestError, ingest_run, upsert_dataset
from app.ingest.resolve import IngredientResolver
from app.models import DrugName, IndiaBrand, IndiaBrandIngredient

log = logging.getLogger("ingest.india_brands")

CURATED = Path(__file__).resolve().parents[2] / "data" / "curated"
INPUT = CURATED / "india_brands.csv"
VERIFIED = CURATED / "india_brands_verified.csv"
INFO = DatasetInfo(
    code="india_brands",
    name="Curated Indian brand names (PrescripTrace)",
    # A file in this repository (each row cites its own public web source).
    source_url="backend/data/curated/india_brands_verified.csv",
    licence="Facts compiled by the project; each row cites its public source page",
    region="IN",
    limitations="Small seed set of common brands. Sources are manufacturer documents or "
    "pharmacy listings (source type shown per row). Brands not in this table are not "
    "recognised: enter the generic name instead.",
)
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
VERIFIED_FIELDS = [
    "brand",
    "dose_form",
    "manufacturer",
    "ingredients",
    "source_type",
    "source_url",
    "source_quote",
    "verified_at",
    "status",
]
# Apollo-style composition line: "Composition AMOXYCILLIN-500MG+CLAVULANIC ACID-125MG".
_COMPOSITION = re.compile(r"(?i)(composition|salt content|each [^.]{0,40}contains)[:\s]+(.{5,160})")


def page_text(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        import pdfplumber

        with pdfplumber.open(io.BytesIO(body)) as pdf:
            text = " ".join(page.extract_text() or "" for page in pdf.pages[:3])
    else:
        html = body.decode("utf-8", "ignore")
        html = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", html)
        text = re.sub(r"<[^>]+>", " ", html)
        import html as html_lib

        text = html_lib.unescape(text)
    return " ".join(text.split())


def quote_for(text: str, terms: list[str]) -> str:
    """The composition statement if present, else the sentence around the first term."""
    match = _COMPOSITION.search(text)
    if match and all(t.lower() in match.group(0).lower() for t in terms[:1]):
        # Drop trailing page furniture after the composition/manufacturer statement.
        return re.split(r"\s(?:Consume Type|3 Step Quality|Therapeutic)", match.group(0))[0][:200]
    idx = text.lower().find(terms[0].lower())
    return text[max(0, idx - 80) : idx + 120]


def verify() -> int:
    rows = list(csv.DictReader(INPUT.open(newline="", encoding="utf-8")))
    out: list[dict[str, str]] = []
    failures = 0
    for row in rows:
        terms = [t.strip() for t in row["page_terms"].split("|") if t.strip()]
        try:
            text = page_text(row["source_url"])
            missing = [t for t in terms if t.lower() not in text.lower()]
            if row["brand"].split()[0].lower() not in text.lower():
                missing.append(f"brand:{row['brand']}")
            status = "verified" if not missing else f"failed: missing {missing}"
            quote = quote_for(text, terms) if not missing else ""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            status, quote = f"failed: fetch error {exc}", ""
        failures += status != "verified"
        log.info("%-20s %s", row["brand"], status)
        out.append(
            {
                **{k: row[k] for k in VERIFIED_FIELDS if k in row},
                "source_quote": quote,
                "verified_at": datetime.now(UTC).date().isoformat(),
                "status": status,
            }
        )
    with VERIFIED.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, VERIFIED_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    log.info("verified %s/%s rows -> %s", len(out) - failures, len(out), VERIFIED.name)
    return failures


def run(session: Session, refresh: bool = False) -> None:
    del refresh
    if not VERIFIED.exists():
        raise IngestError(
            f"{VERIFIED.name} missing: run `python -m app.ingest.india_brands verify`"
        )
    rows = list(csv.DictReader(VERIFIED.open(newline="", encoding="utf-8")))
    dataset = upsert_dataset(session, INFO, downloaded_at=datetime.now(UTC))
    with ingest_run(session, dataset) as stats:
        stats.rows_in = len(rows)
        resolver = IngredientResolver(session)
        old = select(IndiaBrand.id).where(IndiaBrand.dataset_id == dataset.id)
        session.execute(delete(DrugName).where(DrugName.india_brand_id.in_(old)))
        session.execute(delete(IndiaBrand).where(IndiaBrand.dataset_id == dataset.id))
        loaded: list[str] = []
        for row in rows:
            if row["status"] != "verified":
                stats.rows_rejected += 1
                stats.note(f"skip {row['brand']}: {row['status']}")
                continue
            names = [n.strip() for n in row["ingredients"].split(";") if n.strip()]
            resolved = [resolver.resolve(n) for n in names]
            if any(r is None for r in resolved):
                stats.rows_rejected += 1
                missing = [n for n, r in zip(names, resolved, strict=True) if r is None]
                stats.note(f"skip {row['brand']}: ingredient(s) not in RxNorm {missing}")
                continue
            # Ingredients learned from RxNav (e.g. aceclofenac, not US-marketed) must exist
            # before the brand rows reference them.
            resolver.flush_new_ingredients()
            _insert(session, dataset.id, row, [r.rxcui for r in resolved if r is not None])
            loaded.append(row["brand"])
        resolver.flush_new_ingredients()
        stats.rows_out = len(loaded)
        stats.note(f"loaded {len(loaded)} brands")


def _insert(session: Session, ds: int, row: dict[str, Any], rxcuis: list[str]) -> None:
    brand = IndiaBrand(
        brand=row["brand"],
        strength_text=_strength_from_name(row["brand"]),
        dose_form=row["dose_form"] or None,
        manufacturer=row["manufacturer"] or None,
        source_type=row["source_type"],
        source_url=row["source_url"],
        source_quote=row["source_quote"] or None,
        verified_by="fetch-check script; curated list pending pharmacist review",
        verified_at=datetime.fromisoformat(row["verified_at"]).replace(tzinfo=UTC),
        dataset_id=ds,
    )
    session.add(brand)
    session.flush()
    for rxcui in dict.fromkeys(rxcuis):
        session.add(IndiaBrandIngredient(india_brand_id=brand.id, ingredient_rxcui=rxcui))
    session.add(
        DrugName(
            text=row["brand"],
            text_norm=norm(row["brand"]),
            kind="india_brand",
            india_brand_id=brand.id,
            country="IN",
            dataset_id=ds,
            source_ref=f"india_brand:{row['brand']}",
        )
    )


def _strength_from_name(brand: str) -> str | None:
    match = re.search(r"\b(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*$", brand)
    return match.group(1) if match else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if sys.argv[1:] == ["verify"]:
        sys.exit(1 if verify() else 0)
    sys.exit("usage: python -m app.ingest.india_brands verify")
