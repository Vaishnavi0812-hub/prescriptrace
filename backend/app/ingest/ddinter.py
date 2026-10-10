"""DDInter 2.0 drug-drug interactions (primary structured interaction source).

Licence: CC BY-NC-SA 4.0 (non-commercial; derived data shared alike). The download page lists
8 ATC-group files, but 14 exist at the same URL pattern; all are loaded (verified 2026-10-09).
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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
)
from app.ingest.resolve import IngredientResolver
from app.models import Interaction

log = logging.getLogger("ingest.ddinter")

ATC_CODES = "ABCDGHJLMNPRSV"
URL = "https://ddinter2.scbdd.com/static/media/download/ddinter_downloads_code_{}.csv"
DRUG_URL = "https://ddinter2.scbdd.com/server/drug-detail/{}/"
INFO = DatasetInfo(
    code="ddinter",
    name="DDInter 2.0 drug-drug interactions",
    source_url="https://ddinter2.scbdd.com/download/",
    licence="CC BY-NC-SA 4.0 (non-commercial)",
    licence_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
    limitations="Severity levels Major/Moderate/Minor/Unknown only (no 'contraindicated'). "
    "Bulk files carry no mechanism or management text. Absence of a pair is not proof of "
    "safety. Drug names mapped to RxNorm conservatively; unmapped drugs are excluded.",
)

LEVELS = {"major": "major", "moderate": "moderate", "minor": "minor", "unknown": "unknown"}
RANK = {"major": 0, "moderate": 1, "minor": 2, "unknown": 3}
EXPECTED_HEADER = ["DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"]


@dataclass
class _Pair:
    severity: str
    refs: set[str] = field(default_factory=set)
    first_drug_id: str = ""


# DDInter separates route-specific entries, e.g. "Timolol (ophthalmic)" vs "Timolol". Their
# interactions differ from the systemic drug, and our ingredient-level model cannot tell the
# route of a user's medicine, so they are excluded (the systemic entry is still loaded).
ROUTE_WORDS = {
    "topical",
    "ophthalmic",
    "nasal",
    "inhalation",
    "otic",
    "vaginal",
    "rectal",
    "transdermal",
    "intravitreal",
    "intravesical",
    "dental",
    "buccal",
    "oral inhalation",
}
_QUALIFIER = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def split_qualifier(name: str) -> tuple[str, str | None]:
    """'Timolol (ophthalmic)' → ('Timolol', 'ophthalmic'); 'Insulin human (zinc)' →
    ('Insulin human', None): non-route qualifiers name the same ingredient.
    """
    match = _QUALIFIER.match(name)
    if not match:
        return name, None
    base, qualifier = match.group(1), match.group(2).lower()
    if any(word in ROUTE_WORDS for word in re.split(r"[,;]\s*|\s+", qualifier)):
        return base, qualifier
    return base, None


def fetch(refresh: bool = False) -> list[Path]:
    return [
        download(URL.format(code), RAW_DIR / "ddinter" / f"{code}.csv", refresh=refresh)
        for code in ATC_CODES
    ]


def read_rows(paths: list[Path]) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header != EXPECTED_HEADER:
                raise IngestError(f"{path.name}: unexpected header {header} (source changed?)")
            for row in reader:
                if len(row) != 5:
                    raise IngestError(f"{path.name}: malformed row {row!r}")
                rows.append((row[0], row[1].strip(), row[2], row[3].strip(), row[4].strip()))
    return rows


def run(session: Session, refresh: bool = False, report_dir: Path | None = None) -> None:
    paths = fetch(refresh)
    digest = sha256(paths[0])  # files change together; first file's hash marks the version
    dataset = upsert_dataset(
        session, INFO, version="2.0", downloaded_at=datetime.now(UTC), sha256=digest
    )
    with ingest_run(session, dataset) as stats:
        rows = read_rows(paths)
        stats.rows_in = len(rows)
        resolver = IngredientResolver(session)

        names: dict[str, str] = {}
        for id_a, drug_a, id_b, drug_b, _ in rows:
            names[id_a], names[id_b] = drug_a, drug_b
        mapped: dict[str, str] = {}
        unmapped: list[tuple[str, str]] = []
        route_specific = 0
        for i, (ddi_id, name) in enumerate(sorted(names.items())):
            base, route = split_qualifier(name)
            if route is not None:
                route_specific += 1
                unmapped.append((ddi_id, name))
                continue
            resolved = resolver.resolve(base)
            if resolved is None:
                unmapped.append((ddi_id, name))
            else:
                mapped[ddi_id] = resolved.rxcui
            if i % 250 == 0:
                log.info("mapping DDInter drugs %s/%s", i, len(names))
        stats.note(f"Ingredients added from RxNav: {resolver.flush_new_ingredients()}")
        stats.note(
            f"DDInter drugs: {len(names)}, mapped {len(mapped)}, unmapped {len(unmapped)} "
            f"(of which route-specific, excluded by design: {route_specific})"
        )

        pairs: dict[tuple[str, str], _Pair] = {}
        for id_a, _, id_b, _, level in rows:
            severity = LEVELS.get(level.lower())
            if severity is None:
                raise IngestError(f"Unknown DDInter level {level!r}")
            ra, rb = mapped.get(id_a), mapped.get(id_b)
            if ra is None or rb is None or ra == rb:  # unmapped, or two salts of one drug
                stats.rows_rejected += 1
                continue
            key = (ra, rb) if ra < rb else (rb, ra)
            ref = "|".join(sorted((id_a, id_b)))
            pair = pairs.get(key)
            if pair is None:
                pairs[key] = _Pair(severity, {ref}, id_a)
            else:
                pair.refs.add(ref)
                # Several DDInter entries can map to one ingredient pair: keep the most severe
                # known level (a precise level beats "unknown").
                if RANK[severity] < RANK[pair.severity]:
                    pair.severity = severity

        out = [
            {
                "ingredient_a": a,
                "ingredient_b": b,
                "severity": p.severity,
                "provenance": "structured",
                "dataset_id": dataset.id,
                "source_ref": ";".join(sorted(p.refs))[:200],
                "evidence_text": None,
                "source_url": DRUG_URL.format(p.first_drug_id),
            }
            for (a, b), p in pairs.items()
        ]
        table = Interaction.__table__
        stats.rows_out = replace_rows(session, table, dataset.id, out)  # type: ignore[arg-type]
        stats.note(f"Unique ingredient pairs: {len(out)}")

        if report_dir is not None:
            _write_unmapped_report(report_dir / "ddinter_unmapped.csv", unmapped, rows)


def _write_unmapped_report(
    path: Path, unmapped: list[tuple[str, str]], rows: list[tuple[str, str, str, str, str]]
) -> None:
    """Committed transparency report: which DDInter drugs we could not map, and how often."""
    counts: dict[str, int] = {}
    for id_a, _, id_b, _, _ in rows:
        counts[id_a] = counts.get(id_a, 0) + 1
        counts[id_b] = counts.get(id_b, 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ddinter_id", "name", "name_norm", "pairs_lost"])
        for ddi_id, name in sorted(unmapped, key=lambda x: -counts.get(x[0], 0)):
            writer.writerow([ddi_id, name, norm(name), counts.get(ddi_id, 0)])
