"""openFDA drug labels (SPL): label excerpts, label-derived class flags, context notes.

Licence: CC0 / public domain. ~263k labels are streamed (never loaded whole). One
representative label is kept per ingredient combination: the one with the most relevant
sections, then the newest. Class flags and context notes use single-ingredient labels only, so a
warning is never attributed to the wrong ingredient of a combination product.
"""

from __future__ import annotations

import csv
import logging
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import ijson  # type: ignore[import-untyped]
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import (
    RAW_DIR,
    DatasetInfo,
    IngestError,
    cached_json,
    chunks,
    download,
    ingest_run,
    upsert_dataset,
)
from app.ingest.label_rules import context_excerpts, find_flags
from app.ingest.resolve import IngredientResolver
from app.models import ContextNote, DrugClass, IngredientClass, LabelExcerpt

log = logging.getLogger("ingest.labels")

INDEX_URL = "https://api.fda.gov/download.json"
URL = "https://download.open.fda.gov/drug/label/drug-label-{:04d}-of-{:04d}.json.zip"
SETID_URL = "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={}"
INFO = DatasetInfo(
    code="openfda_label",
    name="openFDA drug labels (FDA Structured Product Labeling)",
    source_url="https://open.fda.gov/apis/drug/label/",
    licence="CC0 1.0 / public domain (openFDA)",
    licence_url="https://open.fda.gov/license/",
    region="US",
    limitations="US labels. Class flags (QT, serotonergic, CNS depressant) are found by text "
    "patterns in the drug's own warnings and need human review; context notes quote the label "
    "and are shown as 'check the label', never as dose advice.",
)

SECTIONS = (
    "boxed_warning",
    "contraindications",
    "warnings_and_cautions",
    "warnings",
    "drug_interactions",
    "pregnancy",
    "use_in_specific_populations",
    "pediatric_use",
    "geriatric_use",
    "dosage_and_administration",
)
MAX_SECTION_CHARS = 6000
HUMAN_TYPES = {"HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"}
RESOLVE_THREADS = 6  # RxNav limit is 20 requests/second; latency keeps us well under

FLAG_CLASSES = {
    "qt_prolonging": "QT-prolonging (FDA label warning)",
    "serotonergic": "Serotonergic: serotonin syndrome warning (FDA label)",
    "cns_depressant": "CNS depressant: combined-sedation warning (FDA label)",
}
REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"
REVIEW_FILE = Path(__file__).resolve().parents[2] / "data" / "curated" / "label_flag_review.csv"


@dataclass
class Candidate:
    set_id: str
    ingredients: tuple[str, ...]
    title: str | None
    effective: date | None
    sections: dict[str, str]

    @property
    def score(self) -> tuple[int, date]:
        return (len(self.sections), self.effective or date.min)


def _label_index() -> dict[str, Any]:
    index = cached_json(INDEX_URL, f"openfda/download_index_{date.today().isoformat()}")
    label: dict[str, Any] = index["results"]["drug"]["label"]
    return label


def part_urls() -> list[str]:
    """The number of parts changes between exports; read it from the openFDA index."""
    return [p["file"] for p in _label_index()["partitions"]]


def fetch(refresh: bool) -> list[Path]:
    paths = []
    for url in part_urls():
        paths.append(download(url, RAW_DIR / "openfda" / "label" / Path(url).name, refresh=refresh))
    if not paths:
        raise IngestError("openFDA label index lists no partitions")
    return paths


def iter_labels(path: Path) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".json"))
        with zf.open(name) as fh:
            yield from ijson.items(fh, "results.item")


def _section_text(label: dict[str, Any], name: str) -> str:
    value = label.get(name)
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    return (value or "")[:MAX_SECTION_CHARS]


def _effective(value: str | None) -> date | None:
    try:
        return datetime.strptime(value or "", "%Y%m%d").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def run(session: Session, refresh: bool = False) -> None:
    paths = fetch(refresh)
    dataset = upsert_dataset(session, INFO, downloaded_at=datetime.now(UTC))
    with ingest_run(session, dataset) as stats:
        # Pass 1 (no network): best label per raw substance-name combination.
        by_names: dict[tuple[str, ...], Candidate] = {}
        # no_openfda: FDA has not harmonised the label (no substance names), so its ingredients
        # cannot be identified reliably; mostly repackager/older duplicates of harmonised labels.
        skipped = {"no_openfda": 0, "not_human": 0, "no_substance": 0, "unmapped_substance": 0}
        newest = ""
        for path in paths:
            log.info("streaming %s", path.name)
            for label in iter_labels(path):
                stats.rows_in += 1
                ofda = label.get("openfda") or {}
                if not ofda:
                    skipped["no_openfda"] += 1
                    continue
                if not HUMAN_TYPES & set(ofda.get("product_type") or []):
                    skipped["not_human"] += 1
                    continue
                substances = ofda.get("substance_name") or []
                if not substances:
                    skipped["no_substance"] += 1
                    continue
                key = tuple(sorted({norm(s) for s in substances}))
                cand = Candidate(
                    set_id=label["set_id"],
                    ingredients=key,
                    title=(ofda.get("brand_name") or ofda.get("generic_name") or [None])[0],
                    effective=_effective(label.get("effective_time")),
                    sections={s: t for s in SECTIONS if (t := _section_text(label, s))},
                )
                newest = max(newest, label.get("effective_time") or "")
                if key not in by_names or cand.score > by_names[key].score:
                    by_names[key] = cand
            log.info("%s labels read, %s substance combinations", stats.rows_in, len(by_names))

        # Pass 2: resolve each unique substance name once, in parallel (cached API calls).
        resolver = IngredientResolver(session)
        unique = sorted({n for key in by_names for n in key})
        log.info("resolving %s unique substance names", len(unique))
        with ThreadPoolExecutor(RESOLVE_THREADS) as pool:
            resolved = dict(zip(unique, pool.map(resolver.resolve, unique), strict=True))
        stats.note(f"Ingredients added from RxNav: {resolver.flush_new_ingredients()}")
        unmapped_names = sum(1 for r in resolved.values() if r is None)
        stats.note(f"Substance names: {len(unique)}, unmapped: {unmapped_names}")

        # Pass 3: merge combinations that map to the same ingredient set.
        best: dict[tuple[str, ...], Candidate] = {}
        for names, cand in by_names.items():
            ids = [resolved[n] for n in names]
            if any(r is None for r in ids):
                skipped["unmapped_substance"] += 1  # counts combinations, not labels
                continue
            key = tuple(sorted({r.rxcui for r in ids if r is not None}))
            cand.ingredients = key
            if key not in best or cand.score > best[key].score:
                best[key] = cand
        stats.note(f"Labels read: {stats.rows_in}; skipped: {skipped}")
        stats.rows_rejected = skipped["no_openfda"] + skipped["not_human"] + skipped["no_substance"]
        # openFDA's export date, not the newest effective_time (some labels are future-dated).
        dataset.version = f"openFDA export {_label_index().get('export_date', 'unknown')}"
        stats.note(f"Newest label effective_time seen: {newest}")

        _write_excerpts(session, dataset.id, best)
        flags = _write_flags(session, dataset.id, best, stats)
        notes = _write_context_notes(session, dataset.id, best)
        stats.rows_out = len(best)
        stats.note(
            f"Representative labels: {len(best)} "
            f"(single-ingredient: {sum(1 for k in best if len(k) == 1)}); "
            f"class flags: {flags}; context notes: {notes}"
        )


def _write_excerpts(session: Session, ds: int, best: dict[tuple[str, ...], Candidate]) -> None:
    session.execute(delete(LabelExcerpt).where(LabelExcerpt.dataset_id == ds))
    rows = [
        {
            "set_id": c.set_id,
            "ingredient_rxcuis": list(c.ingredients),
            "title": c.title,
            "effective_time": c.effective,
            "sections": c.sections,
            "dataset_id": ds,
        }
        for c in {c.set_id: c for c in best.values()}.values()  # one set_id can win twice
    ]
    for batch in chunks(rows, 1000):
        session.execute(insert(LabelExcerpt), list(batch))


def _load_review_decisions() -> dict[tuple[str, str], str]:
    """(flag, ingredient rxcui) → accepted | rejected, from the committed human-review file."""
    if not REVIEW_FILE.exists():
        return {}
    with REVIEW_FILE.open(newline="", encoding="utf-8") as fh:
        return {
            (r["flag"], r["ingredient_rxcui"]): r["decision"].strip().lower()
            for r in csv.DictReader(fh)
            if r.get("decision", "").strip().lower() in ("accepted", "rejected")
        }


def _write_flags(
    session: Session, ds: int, best: dict[tuple[str, ...], Candidate], stats: Any
) -> dict[str, int]:
    class_ids: dict[str, int] = {}
    for flag, name in FLAG_CLASSES.items():
        existing = session.scalar(
            select(DrugClass).where(DrugClass.source == "LABEL_FLAG", DrugClass.class_id == flag)
        )
        if existing is None:
            existing = DrugClass(source="LABEL_FLAG", class_id=flag, name=name)
            session.add(existing)
            session.flush()
        class_ids[flag] = existing.id
    session.execute(delete(IngredientClass).where(IngredientClass.dataset_id == ds))

    decisions = _load_review_decisions()
    rows: list[dict[str, Any]] = []
    report: list[list[Any]] = []
    counts = {f: 0 for f in FLAG_CLASSES}
    for key, cand in best.items():
        if len(key) != 1:
            continue
        for hit in find_flags(cand.sections):
            status = decisions.get(
                (hit.flag, key[0]), "needs_review" if hit.needs_review else "auto"
            )
            rows.append(
                {
                    "ingredient_rxcui": key[0],
                    "drug_class_id": class_ids[hit.flag],
                    "dataset_id": ds,
                    "evidence": f"set_id={cand.set_id}; {hit.section}: {hit.sentence}",
                    "review_status": status,
                }
            )
            report.append(
                [hit.flag, key[0], cand.title, cand.set_id, hit.section, hit.sentence, status]
            )
            if status != "rejected":
                counts[hit.flag] += 1
    for batch in chunks(rows):
        session.execute(insert(IngredientClass), list(batch))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "label_flag_candidates.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["flag", "ingredient_rxcui", "label_title", "set_id", "section", "sentence", "status"]
        )
        report.sort(key=lambda r: (str(r[0]), str(r[2])))
        writer.writerows(report)
    stats.note(f"needs_review: {sum(1 for r in rows if r['review_status'] == 'needs_review')}")
    return counts


def _write_context_notes(session: Session, ds: int, best: dict[tuple[str, ...], Candidate]) -> int:
    session.execute(delete(ContextNote).where(ContextNote.dataset_id == ds))
    rows = []
    for key, cand in best.items():
        if len(key) != 1:
            continue
        for context, excerpt in context_excerpts(cand.sections).items():
            rows.append(
                {
                    "ingredient_rxcui": key[0],
                    "context": context,
                    "kind": "check_label",
                    "text": excerpt,
                    "dataset_id": ds,
                    "source_ref": f"set_id={cand.set_id}",
                }
            )
    for batch in chunks(rows):
        session.execute(insert(ContextNote), list(batch))
    return len(rows)
