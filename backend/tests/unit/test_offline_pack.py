"""Offline pack builder, and the shared test vectors for the TypeScript offline engine.

The vectors file holds a pack built from the hand-made snapshot in test_engine.py plus, for a
set of medicine lists, the exact result of the Python engine on the same data. The frontend
test (src/lib/offline/engine.test.ts) runs the TypeScript engine on that pack and must produce
identical findings. If the engine or pack changes, regenerate with:

    UPDATE_VECTORS=1 pytest tests/unit/test_offline_pack.py
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.engine import InteractionFact, Medicine, check, load_rules
from app.core.normalise.vocab import Entry
from app.core.offline_pack import build_pack
from tests.unit.test_engine import KB, fact

VECTORS = Path(__file__).parent.parent / "vectors" / "offline_engine.json"
FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)

# Offline data never includes label quotes or patient context; the snapshot gets two extra
# pairs that must be left out (a moderate pair with an uncommon ingredient, a minor pair).
SNAPSHOT = replace(
    KB,
    context=[],
    labels={},
    interactions=[*KB.interactions, fact("MET", "FUR", "moderate"), fact("TEL", "FUR", "minor")],
)
COMMON = set(KB.names) - {"MET"}
ENTRIES = [
    Entry("Warfarin", "warfarin", "ingredient", ("W",), "ingredient:W", "rxnorm"),
    Entry("Brufen", "brufen", "india_brand", ("IB",), "india_brand:1", "india_brands"),
    Entry("Zerodol-P", "zerodol p", "india_brand", ("ACE", "PCM"), "india_brand:2", "india_brands"),
    Entry("Paracetamol", "paracetamol", "synonym", ("PCM",), "synonym:PCM", "inn_synonyms"),
    Entry("warfarin sodium", "warfarin sodium", "precise", ("W",), "x:1", "rxnorm"),  # not fuzzy
]

CASES: list[tuple[str, list[tuple[str, str, tuple[str, ...]]]]] = [
    ("major pair", [("1", "Warfarin 5", ("W",)), ("2", "Brufen 400", ("IB",))]),
    ("two sources", [("1", "Amiodarone", ("AMI",)), ("2", "Levofloxacin", ("LEV",))]),
    ("moderate common", [("1", "Warfarin", ("W",)), ("2", "Crocin", ("PCM",))]),
    ("moderate uncommon left out", [("1", "Metformin", ("MET",)), ("2", "Lasix", ("FUR",))]),
    (
        "minor and unknown left out",
        [
            ("1", "Telma", ("TEL",)),
            ("2", "Lasix", ("FUR",)),
            ("3", "Brufen", ("IB",)),
            ("4", "Zerodol", ("ACE",)),
        ],
    ),
    ("duplicate ingredient", [("1", "Crocin", ("PCM",)), ("2", "Zerodol-P", ("ACE", "PCM"))]),
    (
        "duplicate class + merge",
        [("1", "Brufen", ("IB",)), ("2", "Zerodol", ("ACE",)), ("3", "Warfarin", ("W",))],
    ),
    (
        "bleeding cumulative",
        [
            ("1", "Warfarin", ("W",)),
            ("2", "Ecosprin", ("AS",)),
            ("3", "Clopilet", ("CL",)),
            ("4", "Brufen", ("IB",)),
        ],
    ),
    (
        "serotonergic",
        [
            ("1", "Sertraline", ("SER",)),
            ("2", "Tramadol", ("TRA",)),
            ("3", "Ondansetron", ("OND",)),
        ],
    ),
    (
        "qt with rejected flag",
        [("1", "Azithral", ("AZI",)), ("2", "Ondansetron", ("OND",)), ("3", "Metformin", ("MET",))],
    ),
    (
        "sedation",
        [("1", "Valium", ("DIA",)), ("2", "Morphine", ("MOR",)), ("3", "Tramadol", ("TRA",))],
    ),
    (
        "potassium",
        [("1", "Lisinopril", ("LIS",)), ("2", "Aldactone", ("SPI",)), ("3", "Telma", ("TEL",))],
    ),
    ("merge: potassium pair", [("1", "Lisinopril", ("LIS",)), ("2", "Aldactone", ("SPI",))]),
    ("merge: bleeding pair", [("1", "Warfarin", ("W",)), ("2", "Ecosprin", ("AS",))]),
    ("merge: serotonin pair", [("1", "Sertraline", ("SER",)), ("2", "Tramadol", ("TRA",))]),
    ("nothing known", [("1", "Metformin", ("MET",)), ("2", "Telma", ("TEL",))]),
    ("single medicine", [("1", "Warfarin", ("W",))]),
]


def _pack() -> dict[str, Any]:
    return build_pack(SNAPSHOT, ENTRIES, load_rules(), COMMON, generated_at=FIXED_TIME)


def _pairs_in(pack: dict[str, Any]) -> set[tuple[str, str]]:
    rx = [row[0] for row in pack["ingredients"]]
    return {(rx[a], rx[b]) for a, b, _ in pack["pairs"]}


def _facts_from(pack: dict[str, Any]) -> list[InteractionFact]:
    """Decode the pack's pairs back into engine facts (also checks the encoding is lossless)."""
    rx = [row[0] for row in pack["ingredients"]]
    out = []
    for a, b, facts in pack["pairs"]:
        for ds, sev, ref, url, *quote in facts:
            out.append(
                InteractionFact(
                    rx[a],
                    rx[b],
                    pack["severities"][sev],
                    "structured",
                    pack["pair_datasets"][ds],
                    ref,
                    None if url is None else pack["url_prefixes"][ds] + url,
                    quote[0] if quote else None,
                )
            )
    return out


def _vectors() -> dict[str, Any]:
    pack = _pack()
    offline_kb = replace(SNAPSHOT, interactions=_facts_from(pack))
    cases = []
    for name, meds in CASES:
        result = check([Medicine(*m) for m in meds], offline_kb)
        cases.append(
            {
                "name": name,
                "medicines": [
                    {"id": i, "label": label, "ingredients": list(rx)} for i, label, rx in meds
                ],
                "expected": {
                    "findings": [asdict(f) for f in result.findings],
                    "checked_pairs": result.checked_pairs,
                    "no_known_issue_pairs": result.no_known_issue_pairs,
                    "counts": result.counts,
                },
            }
        )
    # Round-trip through JSON so tuples compare equal to the stored lists.
    return json.loads(json.dumps({"pack": pack, "cases": cases}))


def test_vectors_are_current() -> None:
    current = _vectors()
    if os.environ.get("UPDATE_VECTORS") == "1":
        VECTORS.parent.mkdir(exist_ok=True)
        text = json.dumps(current, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        VECTORS.write_text(text, encoding="utf-8", newline="\n")
    stored = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert stored == current, "offline vectors are stale: run with UPDATE_VECTORS=1"


def test_pack_facts_match_the_snapshot() -> None:
    def key(f: InteractionFact) -> tuple[Any, ...]:  # pairs are unordered
        return (*sorted((f.a, f.b)), f.severity, f.dataset, f.source_ref, f.source_url)

    kept = _pairs_in(_pack())
    expected = {key(f) for f in SNAPSHOT.interactions if tuple(sorted((f.a, f.b))) in kept}
    assert {key(f) for f in _facts_from(_pack())} == expected


def test_pair_selection() -> None:
    kept = _pairs_in(_pack())
    assert ("IB", "W") in kept  # major
    assert ("PCM", "W") in kept  # moderate, both common
    assert ("FUR", "MET") not in kept  # moderate, metformin not common
    assert ("FUR", "TEL") not in kept  # minor
    assert ("ACE", "IB") not in kept  # ungraded


def test_every_source_record_and_url_survive() -> None:
    pack = _pack()
    rx = [row[0] for row in pack["ingredients"]]
    for a, b, facts in pack["pairs"]:
        if {rx[a], rx[b]} == {"AMI", "LEV"}:
            assert sorted(pack["pair_datasets"][f[0]] for f in facts) == ["ddinter", "medrt"]
            for f in facts:
                prefix = pack["url_prefixes"][f[0]]
                assert prefix + f[3] == "https://x/AMI"


def test_group_membership_comes_from_the_engine() -> None:
    pack = _pack()
    rx = [row[0] for row in pack["ingredients"]]
    qt = {rx[i] for i, _ in pack["groups"]["qt_prolonging"]["members"]}
    assert {"AZI", "OND", "SER"} <= qt
    assert "MET" not in qt  # rejected label flag
    assert "AS" not in {rx[i] for i, _ in pack["groups"]["opioid"]["members"]}  # N02AJ trap
    (azi_evidence,) = [ev for i, ev in pack["groups"]["qt_prolonging"]["members"] if rx[i] == "AZI"]
    assert azi_evidence[0]["dataset"] == "openfda_label" and azi_evidence[0]["url"]


def test_names_only_searchable_kinds() -> None:
    names = {row[0] for row in _pack()["names"]}
    assert {"Brufen", "Zerodol-P", "Paracetamol", "Warfarin"} <= names
    assert "warfarin sodium" not in names


def test_version_changes_with_content() -> None:
    a = _pack()
    b = build_pack(SNAPSHOT, ENTRIES[:2], load_rules(), COMMON, generated_at=FIXED_TIME)
    assert a["version"] != b["version"]
    assert a["version"] == _pack()["version"]
