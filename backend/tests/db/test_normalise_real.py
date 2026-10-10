"""The normaliser on the real loaded vocabulary: the examples from the project brief."""

import pytest

from app.core.normalise import Normaliser
from app.db import _session_factory
from app.repo.vocabulary import load_vocabulary

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]


@pytest.fixture(scope="module")
def normaliser() -> Normaliser:
    session = _session_factory()()
    try:
        vocab = load_vocabulary(session)
    finally:
        session.close()
    if len(vocab.entries) < 1000:
        pytest.skip("vocabulary not loaded (run the ingestion first)")
    return Normaliser(vocab)


@pytest.mark.parametrize(
    ("raw", "ingredients"),
    [
        ("Crocin 650", {"acetaminophen"}),
        ("paracetmol", {"acetaminophen"}),
        ("Paracetamol 500 mg tab", {"acetaminophen"}),
        ("amox/clav", {"amoxicillin", "clavulanate"}),
        ("Augmentin 625", {"amoxicillin", "clavulanate"}),
        ("Augmentin 625 Duo", {"amoxicillin", "clavulanate"}),
        ("Metf0rmin", {"metformin"}),
        ("Tab. Dolo 650 1-0-1 x 5 days", {"acetaminophen"}),
        ("Glycomet 500", {"metformin"}),
        ("Telma 40", {"telmisartan"}),
        ("Zerodol-P", {"aceclofenac", "acetaminophen"}),
        ("salbutamol", {"albuterol"}),
        ("Warfarin 5mg", {"warfarin"}),
        ("Atorvastatin 10", {"atorvastatin"}),
        # Ingredients gap-filled from RxNav must be findable by their own names (Stage 5 fix).
        ("aceclofenac", {"aceclofenac"}),
        ("Domperidone 10 mg", {"domperidone"}),
        ("Nimesulide 100", {"nimesulide"}),
        ("Pantoprazole Tablets IP 40 mg", {"pantoprazole"}),
    ],
)
def test_brief_examples_resolve(normaliser: Normaliser, raw: str, ingredients: set[str]) -> None:
    result = normaliser.normalise(raw)
    assert result.best is not None, f"{raw!r}: {result.status} {result.candidates[:3]}"
    assert set(result.best.ingredient_names) == ingredients
    assert result.status in ("resolved", "confirm")


@pytest.mark.parametrize("raw", ["Pan 40", "xyzzy", "itopride 50"])
def test_unknown_inputs_are_not_guessed(normaliser: Normaliser, raw: str) -> None:
    assert normaliser.normalise(raw).status != "resolved"


def test_crocin_never_resolves_to_saffron(normaliser: Normaliser) -> None:
    result = normaliser.normalise("Crocin")
    assert result.best is not None and result.best.kind == "india_brand"
