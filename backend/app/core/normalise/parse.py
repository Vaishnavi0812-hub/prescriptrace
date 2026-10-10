"""Turn one messy prescription/typed line into match-ready query variants.

Pure functions only. Examples of input this must handle:
  "Crocin 650", "paracetmol", "amox/clav", "Augmentin 625", "Metf0rmin 500mg",
  "Tab. Dolo 650 1-0-1 x 5 days", "Syp Calpol 5 ml TDS".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.text import norm

# Leading list markers and prescription prefixes: "1.", "2)", "Rx", "Tab.", "Cap"
_PREFIX = re.compile(r"^\s*(?:\d{1,2}\s*[.)]\s*|[-•*]\s*|rx\s*[:.]?\s*)+", re.IGNORECASE)

DOSE_FORMS = {
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet",
    "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule",
    "syp": "syrup", "syr": "syrup", "syrup": "syrup",
    "susp": "suspension", "suspension": "suspension",
    "inj": "injection", "injection": "injection",
    "oint": "ointment", "ointment": "ointment", "cream": "cream", "gel": "gel",
    "drop": "drops", "drops": "drops", "sachet": "sachet", "inhaler": "inhaler",
    "soln": "solution", "solution": "solution", "lotion": "lotion", "spray": "spray",
}  # fmt: skip
# Release/variant suffixes. Removed only in the "core" variant: they also appear inside brand
# names (Ondem-MD, Meftal-Spas DS), which are matched first on the full text.
# "od" is handled as a dosing instruction (once daily), its usual meaning on Indian prescriptions.
RELEASE_WORDS = {"sr", "er", "xr", "cr", "xl", "la", "mr", "ds", "dt", "md", "forte"}

# Dosing instructions are not part of the medicine name.
_INSTRUCTIONS = [
    re.compile(r"\b\d\s*-\s*\d\s*-\s*\d(?:\s*-\s*\d)?\b"),  # 1-0-1
    re.compile(r"\b(?:x|for)\s*\d+\s*(?:days?|d|weeks?|wks?|months?)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:od|bd|bid|tds|tid|qid|qds|hs|sos|stat|prn|qd|qhs|once daily|twice daily|"
        r"after food|before food|after meals?|before meals?|at night|morning|evening)\b",
        re.IGNORECASE,
    ),
]
_STRENGTH = re.compile(
    r"(?<![a-z])(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*"
    r"(mg|mcg|µg|ug|g|gm|ml|iu|units?|%)?(?![a-z])",
    re.IGNORECASE,
)
# Combination separators between alphabetic parts: "amox/clav", "paracetamol + ibuprofen".
_COMBO_SPLIT = re.compile(r"\s*(?<=[a-z])\s*(?:/|\+|&|\band\b|\bwith\b)\s*(?=[a-z])", re.IGNORECASE)
# OCR confusions, applied only to a digit sitting between letters ("metf0rmin").
OCR_SUBSTITUTIONS: dict[str, tuple[str, ...]] = {
    "0": ("o",), "1": ("l", "i"), "5": ("s",), "8": ("b",), "6": ("g",), "2": ("z",),
}  # fmt: skip


@dataclass(frozen=True)
class Strength:
    value: str  # "650", "75/40", "0.5"
    unit: str | None  # normalised: "mg", "mcg", "g", "ml", "iu", "unit", "%"


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    full: str  # normalised text, instructions removed, strengths kept ("dolo 650")
    core: str  # strengths, dose forms and release words removed ("dolo")
    strengths: tuple[Strength, ...] = ()
    dose_form: str | None = None
    components: tuple[str, ...] = field(default_factory=tuple)  # combination parts (core text)


def _unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    unit = unit.lower()
    return {"gm": "g", "ug": "mcg", "µg": "mcg", "units": "unit"}.get(unit, unit)


def parse(raw: str) -> ParsedLine:
    text = unicodedata.normalize("NFKC", raw)
    text = _PREFIX.sub("", text)
    for pattern in _INSTRUCTIONS:
        text = pattern.sub(" ", text)
    strengths = tuple(
        Strength(re.sub(r"\s+", "", m.group(1)), _unit(m.group(2)))
        for m in _STRENGTH.finditer(text)
    )
    tokens = norm(text).split()
    dose_form = next((DOSE_FORMS[t] for t in tokens if t in DOSE_FORMS), None)
    # Dose-form words never occur in brand or ingredient names, so drop them everywhere.
    full = " ".join(t for t in tokens if t not in DOSE_FORMS)

    no_strength = _STRENGTH.sub(" ", text)
    parts = [p for p in _COMBO_SPLIT.split(no_strength) if p.strip()]
    components = tuple(c for c in (_core(p) for p in parts) if c) if len(parts) > 1 else ()
    core = _core(no_strength)
    return ParsedLine(raw, full, core, strengths, dose_form, components)


def _core(text: str) -> str:
    words = [
        w
        for w in norm(text).split()
        if w not in DOSE_FORMS and w not in RELEASE_WORDS and not w.isdigit()
    ]
    return " ".join(words)


def ocr_variants(text: str, limit: int = 8) -> list[str]:
    """Spellings with digits-between-letters replaced by look-alike letters."""
    variants = [text]
    # Runs of up to 3 digits inside a word ("amoxici11in"); longer runs are real numbers.
    for match in re.finditer(r"(?<=[a-z])[0-9]{1,3}(?=[a-z])", text):
        for pos in range(match.start(), match.end()):
            options = OCR_SUBSTITUTIONS.get(text[pos])
            if not options:
                continue
            variants = [v[:pos] + ch + v[pos + 1 :] for v in variants for ch in options][:limit]
    return [v for v in variants if v != text]
