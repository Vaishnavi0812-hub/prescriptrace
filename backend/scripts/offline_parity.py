"""Real-data parity check between the Python engine and the TypeScript offline engine.

Builds the real offline pack, draws random medicine lists (biased towards ingredients that have
pairs or rule groups, so most lists produce findings), runs the Python engine on the pack's own
facts, and writes both to data/cache/offline_parity.json. The frontend test
src/lib/offline/parity.test.ts then runs the TypeScript engine on the same lists.

    docker compose run --rm backend python scripts/offline_parity.py [cases]
    cd frontend; npx vitest run src/lib/offline/parity
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

from app.core.engine import InteractionFact, Medicine, check, load_rules
from app.core.offline_pack import build_pack
from app.db import _session_factory
from app.repo.offline import common_ingredients, load_full_snapshot
from app.repo.vocabulary import load_vocabulary

OUT = Path("/data/cache/offline_parity.json")


def main(n_cases: int) -> None:
    session = _session_factory()()
    snapshot = load_full_snapshot(session)
    pack = build_pack(
        snapshot, load_vocabulary(session).entries, load_rules(), common_ingredients(session)
    )
    rx = [row[0] for row in pack["ingredients"]]
    facts = [
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
        for a, b, fs in pack["pairs"]
        for ds, sev, ref, url, *quote in fs
    ]
    # Same classes as the pack's groups were computed from; no labels or context (not offline).
    offline_kb = replace(snapshot, interactions=facts)

    rng = random.Random(20261010)  # noqa: S311 - picks test cases, not security
    pool = sorted({x for a, b, _ in pack["pairs"] for x in (rx[a], rx[b])})
    grouped = sorted({rx[i] for g in pack["groups"].values() for i, _ in g["members"]})
    cases = []
    for n in range(n_cases):
        size = rng.randint(2, 7)
        meds = []
        for i in range(size):
            source = grouped if rng.random() < 0.5 else pool
            k = 2 if rng.random() < 0.15 else 1  # some combination products
            meds.append(Medicine(f"m{i}", f"Medicine {i}", tuple(sorted(rng.sample(source, k)))))
        if n % 10 == 0 and len(meds) > 2:  # some duplicate ingredients across medicines
            meds[-1] = replace(meds[-1], ingredients=meds[0].ingredients)
        result = check(meds, offline_kb)
        cases.append(
            {
                "medicines": [asdict(m) for m in meds],
                "expected": {
                    "findings": [asdict(f) for f in result.findings],
                    "checked_pairs": result.checked_pairs,
                    "no_known_issue_pairs": result.no_known_issue_pairs,
                    "counts": result.counts,
                },
            }
        )
    OUT.write_text(json.dumps({"pack": pack, "cases": cases}), encoding="utf-8")
    found = sum(1 for c in cases if c["expected"]["findings"])
    print(f"wrote {len(cases)} cases ({found} with findings) to {OUT}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
