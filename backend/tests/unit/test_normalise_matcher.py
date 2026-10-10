"""Matcher behaviour on a small hand-built vocabulary (no database)."""

import pytest

from app.core.normalise import Entry, Normaliser, Vocabulary
from app.core.normalise.matcher import Candidate
from app.core.text import norm

ING = {
    "161": "acetaminophen",
    "6809": "metformin",
    "723": "amoxicillin",
    "48203": "clavulanate",
    "2262278": "crocin",
    "5640": "ibuprofen",
    "5553": "hydroxyzine",
    "5470": "hydralazine",
    "40790": "pantoprazole",
    "274783": "insulin glargine",
    "86009": "insulin lispro",
    "5866": "inulin",
    "7896": "pantothenate",
    "10180": "sulfamethoxazole",
    "10829": "trimethoprim",
    "2418": "cholecalciferol",
    "17767": "amlodipine",
    "40827": "iopromide",
}


def e(text: str, kind: str, *ing: str) -> Entry:
    return Entry(text, norm(text), kind, tuple(sorted(ing)), f"{kind}:{text}", "test")


VOCAB = Vocabulary(
    ING,
    [
        *(e(name, "ingredient", rx) for rx, name in ING.items()),
        e("paracetamol", "synonym", "161"),
        e("Augmentin", "brand", "723", "48203"),
        e("Crocin", "india_brand", "161"),
        e("Dolo 650", "india_brand", "161"),
        e("Combiflam", "india_brand", "5640", "161"),
        e("metformin hydrochloride", "synonym", "6809"),
        e("acetaminophen 500 MG Oral Tablet", "product", "161"),
    ],
)


@pytest.fixture
def n() -> Normaliser:
    return Normaliser(VOCAB)


def names(result_best: Candidate | None) -> tuple[str, ...]:
    assert result_best is not None
    return tuple(sorted(result_best.ingredient_names))


def test_exact_full_line(n: Normaliser) -> None:
    r = n.normalise("Dolo 650")
    assert (r.status, r.confidence, r.best and r.best.method) == ("resolved", 1.0, "exact")
    assert names(r.best) == ("acetaminophen",)


def test_india_brand_alias_without_strength(n: Normaliser) -> None:
    r = n.normalise("Tab Dolo 500 1-0-1")
    assert r.status == "resolved"
    assert names(r.best) == ("acetaminophen",)


def test_crocin_is_paracetamol_not_saffron(n: Normaliser) -> None:
    r = n.normalise("Crocin 650")
    assert r.status == "resolved"
    assert r.best is not None and r.best.kind == "india_brand"
    assert names(r.best) == ("acetaminophen",)
    assert r.confidence < 1.0  # same name means two drugs: never full certainty
    assert ("crocin",) in [c.ingredient_names for c in r.candidates]  # alternative shown


def test_brand_with_strength_resolves_to_all_ingredients(n: Normaliser) -> None:
    r = n.normalise("Augmentin 625")
    assert r.status == "resolved"
    assert names(r.best) == ("amoxicillin", "clavulanate")
    assert r.strengths[0].value == "625"


def test_combination_brand(n: Normaliser) -> None:
    assert names(n.normalise("Combiflam").best) == ("acetaminophen", "ibuprofen")


def test_typed_combination_with_abbreviations(n: Normaliser) -> None:
    r = n.normalise("amox/clav 625")
    assert r.status == "resolved"
    assert r.best is not None and r.best.method == "combination"
    assert names(r.best) == ("amoxicillin", "clavulanate")


def test_ocr_digit_fix(n: Normaliser) -> None:
    r = n.normalise("Metf0rmin 500mg")
    assert r.best is not None and r.best.method == "ocr_fix"
    assert names(r.best) == ("metformin",)


def test_misspelling_is_matched_but_flagged(n: Normaliser) -> None:
    r = n.normalise("paracetmol")
    assert r.best is not None and r.best.method == "fuzzy"
    assert names(r.best) == ("acetaminophen",)
    assert r.status in ("resolved", "confirm")


def test_ambiguous_misspelling_is_not_auto_accepted(n: Normaliser) -> None:
    # "hydr...zine" sits between hydroxyzine and hydralazine.
    r = n.normalise("hydrazine")
    assert r.status != "resolved"
    assert {"hydroxyzine", "hydralazine"} <= {c.ingredient_names[0] for c in r.candidates}


def test_short_unknown_token_never_guessed(n: Normaliser) -> None:
    r = n.normalise("Pan 40")
    assert r.status == "unknown"
    assert r.best is None


def test_gibberish_is_unknown(n: Normaliser) -> None:
    r = n.normalise("xqzt lorem")
    assert (r.status, r.candidates) == ("unknown", ())


def test_external_suggestions_are_capped() -> None:
    suggestion = Candidate("Pantocid", "external", ("40790",), ("pantoprazole",), 0.99,
                           "external", "rxnav:1", "rxnav")  # fmt: skip
    r = Normaliser(VOCAB, external=lambda q: [suggestion]).normalise("Pantocid")
    assert r.status == "confirm"
    assert r.confidence == 0.75


def test_deterministic(n: Normaliser) -> None:
    assert n.normalise("paracetmol") == n.normalise("paracetmol")


def test_prefix_shared_by_several_drugs_lists_them_without_picking(n: Normaliser) -> None:
    r = n.normalise("insulin")
    assert r.status == "unknown"  # never "inulin"
    listed = {c.ingredient_names[0] for c in r.candidates}
    assert {"insulin glargine", "insulin lispro"} <= listed


def test_prefix_of_one_drug_asks_to_confirm(n: Normaliser) -> None:
    r = n.normalise("Amlodipin 5")
    assert (r.status, names(r.best)) == ("confirm", ("amlodipine",))


def test_short_ambiguous_prefix(n: Normaliser) -> None:
    r = n.normalise("Panto 40")
    assert r.status == "unknown"
    assert {"pantoprazole", "pantothenate"} <= {c.ingredient_names[0] for c in r.candidates}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Amoxyclav 625", ("amoxicillin", "clavulanate")),
        ("co-trimoxazole", ("sulfamethoxazole", "trimethoprim")),
        ("Vit D3 60000", ("cholecalciferol",)),
    ],
)
def test_abbreviations_including_combinations(
    n: Normaliser, raw: str, expected: tuple[str, ...]
) -> None:
    r = n.normalise(raw)
    assert r.best is not None and r.best.method == "abbreviation"
    assert names(r.best) == expected


def test_weak_lookalike_is_listed_but_not_offered_for_confirmation(n: Normaliser) -> None:
    # itopride is not in RxNorm; iopromide (a contrast agent) only looks similar.
    r = n.normalise("itopride 50")
    assert r.status == "unknown" and r.best is None
    assert ("iopromide",) in [c.ingredient_names for c in r.candidates]


def test_pharmacopoeia_and_unit_noise_is_ignored(n: Normaliser) -> None:
    assert names(n.normalise("Tab. Amlodipine IP 5 mg").best) == ("amlodipine",)
    assert names(n.normalise("Pantoprazole Inj. BP 40 mg").best) == ("pantoprazole",)
