"""Plain-language wording for dataset-backed findings (rule wording lives in rules.yaml).

Rules for all text (tested): grade-8 language, no instruction to stop or change a medicine,
suggest confirming with the prescriber instead.
"""

from __future__ import annotations

PAIR_TITLE = "{a} + {b}"

PAIR_SIMPLE = {
    "contraindicated": "These two medicines are listed as not to be used together.",
    "major": "Taking these two together can cause serious harm.",
    "moderate": "Taking these two together may need extra care or monitoring.",
    "minor": "A minor interaction is known. It is usually low risk.",
    "unknown": "An interaction between these two is listed, but how serious it is has not been "
    "graded in our data.",
}

PAIR_PROFESSIONAL = {
    "contraindicated": "Listed as contraindicated ({sources}).",
    "major": "Major interaction ({sources}).",
    "moderate": "Moderate interaction ({sources}).",
    "minor": "Minor interaction ({sources}).",
    "unknown": "Interaction listed without a severity grade ({sources}).",
}

PAIR_CONSIDER = {
    "contraindicated": "Consider confirming with the prescriber before these are dispensed "
    "together.",
    "major": "Consider confirming with the prescriber before these are dispensed together.",
    "moderate": "Consider checking with the prescriber whether monitoring or spacing the doses "
    "is needed.",
    "minor": "Usually no action is needed. Mention it if the patient has concerns.",
    "unknown": "Consider checking the label or asking the prescriber if unsure.",
}

LABEL_ONLY_SIMPLE = (
    "The official US label of {a} mentions {b} in its drug-interaction section. Our structured "
    "data has no graded interaction for this pair."
)
LABEL_ONLY_PROFESSIONAL = "Mentioned in the FDA label drug-interactions section of {a} (quoted)."
LABEL_ONLY_CONSIDER = "Consider reading the quoted label text, and asking the prescriber if unsure."

CONTEXT_LABEL = {
    "pregnancy": "pregnancy",
    "renal": "kidney problems",
    "hepatic": "liver problems",
    "paediatric": "children",
    "geriatric": "older adults",
}
CONTEXT_TITLE = "{drug}: listed as not suitable with {context}"
CONTEXT_SIMPLE = "{drug} is listed as not suitable for people with {context}."
CONTEXT_PROFESSIONAL = "MED-RT contraindication: {detail}."
CONTEXT_CONSIDER = "Consider confirming with the prescriber whether {drug} is appropriate here."

# Phrases that must never appear in any output text (tested over templates and rules.yaml).
FORBIDDEN_PHRASES = (
    "stop taking",
    "stop the",
    "discontinue",
    "do not take",
    "don't take",
    "must not take",
    "change the dose",
    "reduce the dose",
    "increase the dose",
)
