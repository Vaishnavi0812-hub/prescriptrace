"""Name recognition: does typed text map to the right ingredient(s)?

Cases: data/normalisation_cases.csv (written by hand) plus seeded single-typo variants of the
generic names in it. The expected answer is given as ingredient names and resolved to RxCUIs by
exact name lookup; a case whose expected ingredient is not in our vocabulary counts as a
coverage gap, not as an error of the matcher.

Metrics: top-1 / top-3 accuracy, status mix (resolved = auto-accepted, confirm = user picks,
unknown), and the safety metric "wrong auto-accept" (resolved to the wrong ingredients, or a
non-medicine resolved to anything). External RxNav suggestions are off (reproducible, offline).
"""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from typing import Any

from app.config import get_settings
from app.core.normalise import Normaliser
from app.repo.vocabulary import load_vocabulary

from common import DATA, pct, rxcui_by_name, session, write_result

TYPO_SEED = 20261010
TYPO_CASES = 60


def load_cases() -> list[dict[str, str]]:
    with (DATA / "normalisation_cases.csv").open(encoding="utf-8") as f:
        cases = [dict(row) for row in csv.DictReader(f)]
    return cases + generated_typos(cases)


def generated_typos(cases: list[dict[str, str]]) -> list[dict[str, str]]:
    """One random edit (drop, swap, double or vowel change) in a generic name of 6+ letters."""
    rng = random.Random(TYPO_SEED)  # noqa: S311 - reproducible test data, not security
    names = sorted(
        {
            c["expected"]
            for c in cases
            if c["category"] == "generic"
            and "+" not in c["expected"]
            and " " not in c["expected"]
            and len(c["expected"]) >= 6
        }
    )
    out = []
    for name in rng.sample(names, min(TYPO_CASES, len(names))):
        i = rng.randrange(1, len(name) - 1)
        kind = rng.choice(["drop", "swap", "double", "vowel"])
        if kind == "drop":
            typo = name[:i] + name[i + 1 :]
        elif kind == "swap":
            typo = name[:i] + name[i + 1] + name[i] + name[i + 2 :]
        elif kind == "double":
            typo = name[:i] + name[i] + name[i:]
        else:
            vowels = [j for j, ch in enumerate(name) if ch in "aeiou" and j > 0]
            j = rng.choice(vowels) if vowels else i
            typo = name[:j] + rng.choice([v for v in "aeiou" if v != name[j]]) + name[j + 1 :]
        if typo != name:
            out.append({"text": typo, "expected": name, "category": "typo_generated", "note": kind})
    return out


def run() -> dict[str, Any]:
    s = session()
    try:
        vocab = load_vocabulary(s)
        cases = load_cases()
        wanted = {n.strip() for c in cases for n in c["expected"].split("+") if n.strip()}
        name_to_rx = rxcui_by_name(s, sorted(wanted))
    finally:
        s.close()
    settings = get_settings()
    normaliser = Normaliser(
        vocab,
        auto_accept=settings.normalise_auto_accept,
        confirm_min=settings.normalise_confirm_min,
        external=None,
    )

    rows = []
    for case in cases:
        names = [n.strip() for n in case["expected"].split("+") if n.strip()]
        missing = [n for n in names if n.lower() not in name_to_rx]
        expected = frozenset(name_to_rx[n.lower()] for n in names if n.lower() in name_to_rx)
        line = normaliser.normalise(case["text"])
        candidates = [frozenset(c.ingredients) for c in line.candidates]
        if line.best is not None:
            candidates = [frozenset(line.best.ingredients), *candidates]
        top = list(dict.fromkeys(candidates))
        if missing:
            outcome = "not_in_vocabulary"
        elif not names:  # not a medicine (or not one we can represent)
            outcome = "wrong_auto_accept" if line.status == "resolved" else "correctly_not_resolved"
        elif line.status == "resolved":
            outcome = "correct_auto_accept" if top and top[0] == expected else "wrong_auto_accept"
        elif expected in top[:3]:
            outcome = "user_confirms_correct"
        else:
            outcome = "not_found"
        rows.append(
            {
                **case,
                "status": line.status,
                "confidence": round(line.confidence, 3),
                "top1": bool(top) and top[0] == expected and bool(names),
                "top3": expected in top[:3] and bool(names),
                "outcome": outcome,
                "got": " | ".join(
                    c.label for c in ([line.best] if line.best else []) + list(line.candidates[:3])
                ),
                "missing": ", ".join(missing),
            }
        )

    medicine = [r for r in rows if r["expected"] and not r["missing"]]
    non_medicine = [r for r in rows if not r["expected"]]
    by_category: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["category"]].append(r)
    for cat, rs in sorted(groups.items()):
        scorable = [r for r in rs if r["expected"] and not r["missing"]]
        by_category[cat] = {
            "cases": len(rs),
            "top1_pct": pct(sum(r["top1"] for r in scorable), len(scorable)),
            "top3_pct": pct(sum(r["top3"] for r in scorable), len(scorable)),
            "outcomes": dict(Counter(r["outcome"] for r in rs)),
        }
    wrong = [r for r in rows if r["outcome"] == "wrong_auto_accept"]
    return {
        "cases": len(rows),
        "hand_written": sum(r["category"] != "typo_generated" for r in rows),
        "generated_typos": sum(r["category"] == "typo_generated" for r in rows),
        "thresholds": {
            "auto_accept": settings.normalise_auto_accept,
            "confirm_min": settings.normalise_confirm_min,
        },
        "medicine_cases_scored": len(medicine),
        "top1_pct": pct(sum(r["top1"] for r in medicine), len(medicine)),
        "top3_pct": pct(sum(r["top3"] for r in medicine), len(medicine)),
        "auto_accepted_pct": pct(sum(r["status"] == "resolved" for r in medicine), len(medicine)),
        "wrong_auto_accept": len(wrong),
        "wrong_auto_accept_pct_of_all": pct(len(wrong), len(rows)),
        "non_medicine_cases": len(non_medicine),
        "non_medicine_resolved": sum(r["status"] == "resolved" for r in non_medicine),
        "not_in_vocabulary": [r["text"] + " → " + r["missing"] for r in rows if r["missing"]],
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "by_category": by_category,
        "wrong_auto_accepts": [{k: r[k] for k in ("text", "expected", "got")} for r in wrong],
        "not_found": [
            {k: r[k] for k in ("text", "expected", "status", "got")}
            for r in rows
            if r["outcome"] == "not_found"
        ],
        "rows": rows,
    }


def main() -> None:
    result = run()
    path = write_result("normalisation", result)
    keys = (
        "cases",
        "top1_pct",
        "top3_pct",
        "auto_accepted_pct",
        "wrong_auto_accept",
        "non_medicine_resolved",
        "outcomes",
    )
    for k in keys:
        print(f"{k}: {result[k]}")
    print("wrong auto-accepts:", result["wrong_auto_accepts"])
    print("not found:", result["not_found"])
    print("not in vocabulary:", result["not_in_vocabulary"])
    print(
        "by category:",
        {k: (v["top1_pct"], v["top3_pct"]) for k, v in result["by_category"].items()},
    )
    print("written", path)


if __name__ == "__main__":
    main()
