"""Shared helpers for the evaluation harness (runs inside the backend container)."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db import _session_factory
from app.models import Dataset, Ingredient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"
RAW = Path("/data/raw")


def session() -> Session:
    return _session_factory()()


def rxcui_by_name(s: Session, names: list[str]) -> dict[str, str]:
    """Exact (case-insensitive) ingredient-name lookup. Never fuzzy: the reference must not
    depend on the system being evaluated."""
    lowered = [n.lower() for n in names]
    rows = s.execute(
        select(func.lower(Ingredient.name), Ingredient.rxcui).where(
            func.lower(Ingredient.name).in_(lowered)
        )
    )
    return dict(rows.tuples().all())


def dataset_versions(s: Session) -> dict[str, str | None]:
    return {d.code: d.version for d in s.scalars(select(Dataset))}


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summary_ms(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50_ms": round(percentile(values, 50), 1),
        "p95_ms": round(percentile(values, 95), 1),
        "mean_ms": round(statistics.fmean(values), 1),
        "max_ms": round(max(values), 1),
    }


def write_result(name: str, body: dict[str, Any]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    s = session()
    try:
        body = {
            "evaluation": name,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "dataset_versions": dataset_versions(s),
            **body,
        }
    finally:
        s.close()
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
