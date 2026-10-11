"""Server-side latency of each API call (in-process, so network time is NOT included).

Runs the real FastAPI app with TestClient against the loaded database, sequentially, after a
warm-up call. Rate limits are switched off for the run. Also reports response sizes (gzipped,
as sent to the phone).
"""

from __future__ import annotations

import gzip
import os
import random
import time
from typing import Any

os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["NORMALISE_EXTERNAL"] = "false"
os.environ["OFFLINE_PACK_PREBUILD"] = "false"

from app.core.ocr.synthetic import render
from app.main import app
from fastapi.testclient import TestClient

from common import rxcui_by_name, session, summary_ms, write_result

RUNS = 50
OCR_RUNS = 10
SEED = 7
COMMON = [
    "warfarin",
    "aspirin",
    "clopidogrel",
    "ibuprofen",
    "acetaminophen",
    "metformin",
    "atorvastatin",
    "amlodipine",
    "telmisartan",
    "sertraline",
    "tramadol",
    "ondansetron",
    "azithromycin",
    "levofloxacin",
    "furosemide",
    "spironolactone",
    "lisinopril",
    "omeprazole",
    "pantoprazole",
    "prednisolone",
    "digoxin",
    "amiodarone",
]
QUERIES = ["dolo", "paracetmol", "telma", "amlod", "warf", "azithr", "pan 40", "metfor"]
LINES = ["Dolo 650", "Tab Telma 40 0-0-1", "amlodepine 5", "Pan 40", "warfarin 5mg"]


def timed(fn: Any) -> tuple[float, Any]:
    started = time.perf_counter()
    out = fn()
    return (time.perf_counter() - started) * 1000, out


def run() -> dict[str, Any]:
    s = session()
    try:
        rx = rxcui_by_name(s, COMMON)
    finally:
        s.close()
    rng = random.Random(SEED)  # noqa: S311 - picks test inputs
    results: dict[str, Any] = {}
    sizes: dict[str, int] = {}
    with TestClient(app) as client:

        def measure(name: str, call: Any, runs: int = RUNS) -> None:
            call(0)  # warm-up
            times = []
            for i in range(runs):
                ms, response = timed(lambda i=i: call(i))
                assert response.status_code == 200, (name, response.text[:200])
                times.append(ms)
            results[name] = summary_ms(times)
            sizes[name] = len(gzip.compress(response.content))

        measure(
            "search",
            lambda i: client.get("/api/v1/drugs/search", params={"q": QUERIES[i % len(QUERIES)]}),
        )
        measure(
            "normalise_5_lines", lambda i: client.post("/api/v1/normalise", json={"lines": LINES})
        )
        for n in (2, 5, 10):

            def check(i: int, n: int = n) -> Any:
                picked = rng.sample(sorted(rx), n)
                items = [
                    {
                        "id": f"m{k}",
                        "text": name,
                        "selection": {"ref": None, "label": name, "ingredients": [rx[name]]},
                    }
                    for k, name in enumerate(picked)
                ]
                return client.post("/api/v1/check", json={"items": items, "context": {}})

            measure(f"check_{n}_medicines", check)
        page = render(["Tab Dolo 650 1-0-1", "Tab Telma 40 0-0-1", "Cap Pantop 40 1-0-0"])
        measure(
            "ocr_printed_page",
            lambda i: client.post("/api/v1/ocr", files={"file": ("rx.png", page, "image/png")}),
            OCR_RUNS,
        )
        pack_ms, pack = timed(
            lambda: client.get("/api/v1/offline-pack", headers={"Accept-Encoding": "gzip"})
        )
        results["offline_pack_first_build_ms"] = round(pack_ms, 1)
        assert pack.status_code == 200
        # The test client un-gzips bodies, so take the served size from the server itself.
        sizes["offline_pack"] = client.get("/api/v1/offline-pack/meta").json()["download_bytes"]
    return {
        "method": "in-process TestClient, sequential, after warm-up; network time not included",
        "runs": RUNS,
        "latency": results,
        "response_bytes_gzipped": sizes,
    }


def main() -> None:
    result = run()
    path = write_result("latency", result)
    for k, v in result["latency"].items():
        print(k, v)
    print("sizes:", result["response_bytes_gzipped"])
    print("written", path)


if __name__ == "__main__":
    main()
