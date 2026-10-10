"""Curated international (INN/BAN) drug names used in India, e.g. paracetamol, salbutamol.

data/curated/inn_synonyms.csv lists name → expected RxNorm ingredient. A synonym is loaded only
if RxNav finds the name as an exact string in one of its source vocabularies (e.g. ATC) AND it
maps to the expected ingredient. Anything else is rejected and reported, so a typo in the
curated file cannot create a wrong mapping.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import DatasetInfo, ingest_run, upsert_dataset
from app.ingest.resolve import IngredientResolver
from app.models import DrugName

CURATED = Path(__file__).resolve().parents[2] / "data" / "curated" / "inn_synonyms.csv"
INFO = DatasetInfo(
    code="inn_synonyms",
    name="International / British drug names common in India (curated, RxNav-verified)",
    source_url="https://rxnav.nlm.nih.gov/ (exact-match verification of each name)",
    licence="Names verified against RxNorm source vocabularies via RxNav (public domain)",
    region="IN",
    limitations="Only names that RxNav knows exactly and that map to the expected ingredient "
    "are loaded; rejected rows are listed in the ingest log.",
)


def run(session: Session, refresh: bool = False) -> None:
    del refresh
    rows = list(csv.DictReader(CURATED.open(newline="", encoding="utf-8")))
    dataset = upsert_dataset(session, INFO, downloaded_at=datetime.now(UTC))
    with ingest_run(session, dataset) as stats:
        stats.rows_in = len(rows)
        resolver = IngredientResolver(session)
        out = []
        for row in rows:
            name, expected = row["name"].strip(), norm(row["expected_ingredient"])
            resolved = resolver.resolve(name)
            if resolved is None:
                stats.rows_rejected += 1
                stats.note(f"reject {name!r}: not found exactly in RxNav")
                continue
            if norm(resolved.name) != expected:
                stats.rows_rejected += 1
                stats.note(f"reject {name!r}: maps to {resolved.name!r}, expected {expected!r}")
                continue
            if norm(name) == norm(resolved.name):
                continue  # already the RxNorm name; nothing to add
            out.append(
                {
                    "text": name,
                    "text_norm": norm(name),
                    "kind": "synonym",
                    "ingredient_rxcui": resolved.rxcui,
                    "country": "IN",
                    "dataset_id": dataset.id,
                    "source_ref": f"curated INN; RxNav exact → RXCUI:{resolved.rxcui}",
                }
            )
        resolver.flush_new_ingredients()
        session.execute(delete(DrugName).where(DrugName.dataset_id == dataset.id))
        if out:
            session.execute(insert(DrugName), out)
        stats.rows_out = len(out)
        stats.note(f"synonyms loaded: {len(out)}")
