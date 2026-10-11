"""Run the evaluation harness. Inside the backend container:

    docker compose run --rm backend python /evaluation/run.py [PART ...]

PART is normalisation, interactions, ocr, latency or all (the default).

Each part writes results/<name>.json; the report (results/REPORT.md) is rebuilt at the end.
"""

from __future__ import annotations

import sys

import eval_interactions
import eval_latency
import eval_normalisation
import eval_ocr
import report

PARTS = {
    "normalisation": eval_normalisation.main,
    "interactions": eval_interactions.main,
    "ocr": eval_ocr.main,
    "latency": eval_latency.main,
}


def main() -> None:
    wanted = sys.argv[1:] or ["all"]
    for name in PARTS if "all" in wanted else wanted:
        if name not in PARTS:
            raise SystemExit(f"unknown part {name!r}; choose from {', '.join(PARTS)} or all")
        print(f"=== {name} ===")
        PARTS[name]()
    report.main()


if __name__ == "__main__":
    main()
