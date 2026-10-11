"""Prescription reading (OCR): printed pages, and a handwriting-style stand-in.

Pages are rendered by app/core/ocr/synthetic.py (invented clinic/patient header, real medicine
names), with seeded random medicine lines. "Printed" variants: clean sans, serif, rotated, blurred,
speckled, small/low-resolution. "Handwriting-style" variants use two handwriting fonts (Kalam,
Caveat; SIL OFL) as a stand-in: they are far more regular than real handwriting, so these numbers
are an UPPER BOUND for real handwritten prescriptions, which we could not test (no real,
consented samples). Each page goes through the real pipeline (pre-processing, Tesseract,
line classification, name matching).

Per medicine line: character error rate (CER) of the best-matching OCR line; outcome =
auto-added correctly / user confirms the right one (top 3) / wrong auto-accept (safety) /
missed. Per page: non-medicine lines wrongly offered as medicines.
"""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.core.normalise import Normaliser
from app.core.ocr import scan
from app.core.ocr.synthetic import render
from app.repo.vocabulary import load_vocabulary
from app.services.ocr_service import get_engine
from rapidfuzz.distance import Levenshtein

from common import RAW, pct, rxcui_by_name, session, summary_ms, write_result

SEED = 20261011
PAGES_PER_VARIANT = 6
FONTS = RAW / "fonts"

# (line as written on the prescription, expected ingredients)
LINES: list[tuple[str, str]] = [
    ("Tab Dolo 650 1-0-1 x 5 days", "acetaminophen"),
    ("Tab Pantop 40 1-0-0 before food", "pantoprazole"),
    ("Tab Telma 40 0-0-1", "telmisartan"),
    ("Tab Ecosprin 75 0-1-0", "aspirin"),
    ("Cap Amoxicillin 500 1-1-1 x 5 days", "amoxicillin"),
    ("Tab Azithral 500 1-0-0 x 3 days", "azithromycin"),
    ("Tab Glycomet 500 1-0-1", "metformin"),
    ("Tab Atorvastatin 10 0-0-1", "atorvastatin"),
    ("Tab Amlodipine 5 1-0-0", "amlodipine"),
    ("Tab Cetirizine 10 0-0-1", "cetirizine"),
    ("Tab Montelukast 10 0-0-1", "montelukast"),
    ("Tab Metoprolol 25 1-0-1", "metoprolol"),
    ("Tab Clopilet 75 0-1-0", "clopidogrel"),
    ("Tab Thyronorm 50 1-0-0 empty stomach", "levothyroxine"),
    ("Tab Losartan 50 1-0-0", "losartan"),
    ("Syp Ondansetron 5 ml SOS", "ondansetron"),
    ("Tab Metronidazole 400 1-1-1", "metronidazole"),
    ("Tab Combiflam 1-0-1 after food", "ibuprofen+acetaminophen"),
    ("Tab Warfarin 5 0-0-1", "warfarin"),
    ("Tab Sertraline 50 0-0-1", "sertraline"),
]

VARIANTS: dict[str, dict[str, Any]] = {
    "printed_clean": {},
    "printed_serif": {"serif": True},
    "printed_rotated_5deg": {"rotate": 5.0},
    "printed_blur": {"blur": 1.2},
    "printed_speckle": {"noise": 0.02},
    "printed_small": {"width": 820, "font_size": 22},
    "handwriting_style_kalam": {"font": "Kalam-Regular.ttf"},
    "handwriting_style_caveat": {"font": "Caveat-VF.ttf", "font_size": 40},
    "handwriting_style_kalam_rotated_blur": {
        "font": "Kalam-Regular.ttf",
        "rotate": 3.0,
        "blur": 0.8,
    },
}


def run() -> dict[str, Any]:
    s = session()
    try:
        vocab = load_vocabulary(s)
        names = sorted({n for _, e in LINES for n in e.split("+")})
        to_rx = rxcui_by_name(s, names)
    finally:
        s.close()
    missing = [n for n in names if n not in to_rx]
    if missing:
        raise SystemExit(f"reference ingredients not in vocabulary: {missing}")
    settings = get_settings()
    normaliser = Normaliser(
        vocab,
        auto_accept=settings.normalise_auto_accept,
        confirm_min=settings.normalise_confirm_min,
        external=None,
    )
    engine = get_engine()
    rng = random.Random(SEED)  # noqa: S311 - reproducible test pages

    per_variant: dict[str, dict[str, Any]] = {}
    all_lines: list[dict[str, Any]] = []
    for variant, opts in VARIANTS.items():
        opts = dict(opts)
        font = opts.pop("font", None)
        if font and not (FONTS / font).exists():
            raise SystemExit(f"missing font {FONTS / font} (see METHODOLOGY.md for the download)")
        outcomes: Counter[str] = Counter()
        cers: list[float] = []
        millis: list[float] = []
        false_medicine_lines = 0
        for page_no in range(PAGES_PER_VARIANT):
            chosen = rng.sample(LINES, rng.randint(3, 4))
            image = render(
                [text for text, _ in chosen],
                seed=page_no,
                font_path=Path(FONTS / font) if font else None,
                **opts,
            )
            started = time.perf_counter()
            result = scan(image, engine, normaliser)
            millis.append((time.perf_counter() - started) * 1000)
            used: set[int] = set()
            for i, (text, expected) in enumerate(chosen, 1):
                truth = f"{i}. {text}"
                want = frozenset(to_rx[n] for n in expected.split("+"))
                # The OCR line closest to this prescription line.
                scored = [
                    (Levenshtein.normalized_distance(truth.lower(), ln.text.lower()), k)
                    for k, ln in enumerate(result.lines)
                    if k not in used
                ]
                if not scored:
                    outcome, cer = "missed", 1.0
                else:
                    cer, k = min(scored)
                    used.add(k)
                    line = result.lines[k]
                    norm = line.normalised
                    cands = [frozenset(c.ingredients) for c in (norm.candidates if norm else [])]
                    best = frozenset(norm.best.ingredients) if norm and norm.best else None
                    if not line.likely_medicine:
                        outcome = "missed"  # shown only under "other text"
                    elif line.status == "resolved":
                        outcome = "auto_correct" if best == want else "wrong_auto_accept"
                    elif want in ([best] if best else []) + cands[:3]:
                        outcome = "confirm_correct"
                    else:
                        outcome = "missed"
                outcomes[outcome] += 1
                cers.append(cer)
                all_lines.append(
                    {"variant": variant, "truth": truth, "outcome": outcome, "cer": round(cer, 3)}
                )
            false_medicine_lines += sum(
                1 for k, ln in enumerate(result.lines) if ln.likely_medicine and k not in used
            )
        n = sum(outcomes.values())
        per_variant[variant] = {
            "medicine_lines": n,
            "auto_correct_pct": pct(outcomes["auto_correct"], n),
            "found_correct_pct": pct(outcomes["auto_correct"] + outcomes["confirm_correct"], n),
            "wrong_auto_accept": outcomes["wrong_auto_accept"],
            "missed_pct": pct(outcomes["missed"], n),
            "median_cer": round(sorted(cers)[len(cers) // 2], 3),
            "false_medicine_lines": false_medicine_lines,
            "page_time": summary_ms(millis),
        }

    def group(prefix: str) -> dict[str, Any]:
        rows = [r for r in all_lines if r["variant"].startswith(prefix)]
        c = Counter(r["outcome"] for r in rows)
        return {
            "medicine_lines": len(rows),
            "auto_correct_pct": pct(c["auto_correct"], len(rows)),
            "found_correct_pct": pct(c["auto_correct"] + c["confirm_correct"], len(rows)),
            "wrong_auto_accept": c["wrong_auto_accept"],
            "missed_pct": pct(c["missed"], len(rows)),
        }

    missed: dict[str, list[str]] = defaultdict(list)
    for r in all_lines:
        if r["outcome"] != "auto_correct" and r["outcome"] != "confirm_correct":
            missed[r["variant"]].append(f"{r['truth']} ({r['outcome']}, CER {r['cer']})")
    return {
        "engine": engine.name,
        "pages_per_variant": PAGES_PER_VARIANT,
        "printed": group("printed"),
        "handwriting_style": group("handwriting_style"),
        "by_variant": per_variant,
        "not_found_examples": {k: v[:8] for k, v in missed.items()},
        "note": "handwriting_style uses handwriting fonts, not real handwriting: an upper bound.",
    }


def main() -> None:
    result = run()
    path = write_result("ocr", result)
    print("printed:", result["printed"])
    print("handwriting_style:", result["handwriting_style"])
    for k, v in result["by_variant"].items():
        print(
            f"  {k}: found {v['found_correct_pct']}% auto {v['auto_correct_pct']}% "
            f"wrong {v['wrong_auto_accept']} CER {v['median_cer']} "
            f"extra {v['false_medicine_lines']} p50 {v['page_time']['p50_ms']}ms"
        )
    print("not found:", result["not_found_examples"])
    print("written", path)


if __name__ == "__main__":
    main()
