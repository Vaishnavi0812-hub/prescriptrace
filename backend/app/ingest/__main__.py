"""CLI: python -m app.ingest <source> [<source> ...] [--refresh]

Sources run in dependency order regardless of the order given. `all` runs everything.
Every source is idempotent: re-running replaces that source's rows.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from app.db import _session_factory
from app.ingest import (
    ddinter,
    india_brands,
    openfda_labels,
    openfda_recalls,
    rxclass,
    rxnorm,
    synonyms,
)
from app.ingest.common import IngestError

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

SOURCES: dict[str, Callable[..., None]] = {
    "rxnorm": rxnorm.run,
    "ddinter": lambda s, refresh: ddinter.run(s, refresh, report_dir=REPORT_DIR),
    "recalls": openfda_recalls.run,
    "labels": openfda_labels.run,
    "classes": rxclass.run,
    "india_brands": india_brands.run,
    "synonyms": synonyms.run,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest", description=__doc__)
    parser.add_argument("sources", nargs="+", choices=[*SOURCES, "all"])
    parser.add_argument("--refresh", action="store_true", help="re-download source files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    wanted = list(SOURCES) if "all" in args.sources else args.sources
    for name in [s for s in SOURCES if s in wanted]:  # dependency order
        started = time.monotonic()
        logging.info("=== %s ===", name)
        session = _session_factory()()
        try:
            SOURCES[name](session, args.refresh)
        except IngestError as exc:
            logging.error("%s FAILED: %s", name, exc)
            return 1
        finally:
            session.close()
        logging.info("=== %s done in %.0fs ===", name, time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
