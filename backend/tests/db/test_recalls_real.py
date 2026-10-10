"""Recall flagging on real loaded data (CDSCO + openFDA)."""

import pytest

from app.core.normalise import Normaliser
from app.core.recalls import MedicineRef, check_recalls
from app.db import _session_factory
from app.repo.recalls import load_recalls
from app.repo.vocabulary import load_vocabulary

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]


@pytest.fixture(scope="module")
def session():  # type: ignore[no-untyped-def]
    s = _session_factory()()
    yield s
    s.close()


@pytest.fixture(scope="module")
def normaliser(session) -> Normaliser:  # type: ignore[no-untyped-def]
    vocab = load_vocabulary(session)
    if len(vocab.entries) < 1000:
        pytest.skip("vocabulary not loaded")
    return Normaliser(vocab)


def med(normaliser: Normaliser, text: str, batch: str | None = None) -> MedicineRef:
    result = normaliser.normalise(text)
    assert result.best is not None
    return MedicineRef("1", text, result.best.ingredients, (text, result.best.label), batch=batch)


def run(session, m: MedicineRef):  # type: ignore[no-untyped-def]
    records, datasets = load_recalls(session, m.ingredients, m.brand_names)
    return check_recalls([m], records, datasets)


def need_cdsco(session) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    if not session.scalar(text("select count(*) from dataset where code='cdsco_alerts'")):
        pytest.skip("CDSCO alerts not loaded")


def test_counterfeit_telma_batch_is_flagged(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    need_cdsco(session)
    result = run(session, med(normaliser, "Telma 40", batch="K18230707"))
    first = result.flags[0]
    assert (first.match, first.level, first.region) == ("batch", "serious", "IN")
    assert "Spurious" in first.kind
    assert first.evidence.url and first.evidence.url.startswith("https://cdsco.gov.in/")


def test_telma_without_batch_points_to_brand_alert(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    need_cdsco(session)
    result = run(session, med(normaliser, "Telma 40"))
    matches = {(f.match, f.product_description.split(" (")[0]) for f in result.flags}
    assert any(m == "product" for m, _ in matches)  # the Telma 40 batches
    assert ("related", "Telma H") in matches  # same brand family, different product
    assert not [f for f in result.flags if f.match == "batch"]


def test_paracetamol_us_recalls_are_information_only(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    result = run(session, med(normaliser, "Dolo 650"))
    us = [s for s in result.ingredient_summaries if s.region == "US"]
    assert us and us[0].total > 10
    assert all(f.level == "info" for s in result.ingredient_summaries for f in s.recent)
    assert not [f for f in result.flags if f.region == "US"]


def test_checklist_always_returned(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    assert run(session, med(normaliser, "Metformin 500")).checklist
