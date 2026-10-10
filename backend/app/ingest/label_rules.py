"""Pure text rules for FDA label sections: class flags and patient-context excerpts.

Every output carries the exact sentence it came from, so a reviewer (and the user) can see why
a flag exists. Rules are intentionally narrow: a missed flag is listed in the evaluation, a
wrong flag would put a false warning in front of a pharmacist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Sections searched for class flags (the drug's own warnings, not its interaction partners).
FLAG_SECTIONS = ("boxed_warning", "warnings_and_cautions", "warnings", "contraindications")

FLAG_PATTERNS: dict[str, re.Pattern[str]] = {
    # "QT prolongation", "prolongation of the QT interval", "prolong the QTc", "torsade(s)"
    "qt_prolonging": re.compile(
        r"\bQTc?\b[^.]{0,40}\bprolong|\bprolong\w*\b[^.]{0,40}\bQTc?\b|torsade", re.IGNORECASE
    ),
    "serotonergic": re.compile(r"serotonin syndrome", re.IGNORECASE),
    # Opioid / benzodiazepine boxed-warning language about combined sedation.
    "cns_depressant": re.compile(
        r"profound sedation|\bCNS depressant|central nervous system depressant", re.IGNORECASE
    ),
}

# The flagged effect is described as absent or only theoretical → a human must decide.
# The label denies the effect ("did not prolong the QTc", "no effect on QT") → human decides.
# "Not recommended with other QT-prolonging drugs" is NOT a denial and must not match.
NEGATION = re.compile(
    r"\b(did not|does not|do not|no clinically (relevant|significant|meaningful)|"
    r"no (meaningful |significant )?effect on|not associated with|was not observed)\b"
    r"[^.]{0,60}(prolong|QT|serotonin|sedation)",
    re.IGNORECASE,
)
# Mentioned only as something to rule out, e.g. metoclopramide's NMS differential diagnosis.
DIFFERENTIAL = re.compile(r"differential diagnosis", re.IGNORECASE)
EVIDENCE_WINDOW = 180  # characters either side of the match

CONTEXT_PATTERNS: dict[str, re.Pattern[str]] = {
    "renal": re.compile(r"renal impairment|kidney (impairment|disease)|creatinine clearance", re.I),
    "hepatic": re.compile(r"hepatic impairment|liver (impairment|disease)|child-pugh", re.I),
}
# Whole-section excerpts for these contexts.
CONTEXT_SECTIONS = {
    "pregnancy": ("pregnancy",),
    "paediatric": ("pediatric_use",),
    "geriatric": ("geriatric_use",),
}
CONTEXT_SEARCH_SECTIONS = (
    "use_in_specific_populations",
    "dosage_and_administration",
    "warnings_and_cautions",
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
# Labels start sections with headings like "8.1 Pregnancy Risk Summary".
_HEADING = re.compile(r"^\s*(\d+(\.\d+)*\s+)?[A-Z][A-Za-z &/-]{0,60}\s+(?=[A-Z])")
MAX_EXCERPT = 600


@dataclass(frozen=True)
class FlagHit:
    flag: str
    section: str
    sentence: str
    needs_review: bool


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(" ".join(text.split())) if s.strip()]


def find_flags(sections: dict[str, str]) -> list[FlagHit]:
    """First match per flag, with the text around the match as evidence.

    needs_review when the text denies the effect or only lists it in a differential diagnosis.
    An affirmative hit replaces an earlier needs_review hit for the same flag.
    """
    hits: dict[str, FlagHit] = {}
    for section in FLAG_SECTIONS:
        for sentence in sentences(sections.get(section, "")):
            for flag, pattern in FLAG_PATTERNS.items():
                if flag in hits and not hits[flag].needs_review:
                    continue
                match = pattern.search(sentence)
                if match is None:
                    continue
                start = max(0, match.start() - EVIDENCE_WINDOW)
                window = sentence[start : match.end() + EVIDENCE_WINDOW]
                doubtful = bool(NEGATION.search(window) or DIFFERENTIAL.search(window))
                evidence = ("… " if start else "") + window.strip()
                hit = FlagHit(flag, section, evidence[:420], doubtful)
                if flag not in hits or not hit.needs_review:
                    hits[flag] = hit
    return list(hits.values())


def context_excerpts(sections: dict[str, str]) -> dict[str, str]:
    """Patient-context excerpts quoted from the label (never paraphrased, never computed)."""
    out: dict[str, str] = {}
    for context, names in CONTEXT_SECTIONS.items():
        for name in names:
            text = " ".join(sections.get(name, "").split())
            if text:
                out[context] = _trim(text)
                break
    for context, pattern in CONTEXT_PATTERNS.items():
        for name in CONTEXT_SEARCH_SECTIONS:
            matched = [s for s in sentences(sections.get(name, "")) if pattern.search(s)]
            if matched:
                out[context] = _trim(" ".join(matched[:2]))
                break
    return out


def _trim(text: str) -> str:
    if len(text) <= MAX_EXCERPT:
        return text
    cut = text[:MAX_EXCERPT].rsplit(" ", 1)[0]
    return cut + " …"
