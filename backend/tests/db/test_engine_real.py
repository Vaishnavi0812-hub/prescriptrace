"""End-to-end on real data: typed names -> normaliser -> knowledge snapshot -> engine."""

import pytest
from sqlalchemy import select

from app.core.engine import Medicine, PatientContext, check, load_rules
from app.core.normalise import Normaliser
from app.db import _session_factory
from app.models import DrugClass, Ingredient
from app.repo.knowledge import load_snapshot
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


def run(session, normaliser, *lines: str, ctx: PatientContext | None = None):  # type: ignore[no-untyped-def]
    meds = []
    for i, line in enumerate(lines):
        r = normaliser.normalise(line)
        assert r.best is not None, f"could not resolve {line!r}"
        meds.append(Medicine(str(i), line, r.best.ingredients))
    snapshot = load_snapshot(session, {rx for m in meds for rx in m.ingredients})
    return check(meds, snapshot, ctx)


def rule_ids(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.rule_id for f in result.findings if f.rule_id} | {
        r for f in result.findings for r in f.related_rules
    }


def test_every_rule_selector_exists_in_loaded_data(session) -> None:  # type: ignore[no-untyped-def]
    rules = load_rules()
    epc = set(session.scalars(select(DrugClass.name).where(DrugClass.source == "EPC")))
    atc = set(session.scalars(select(DrugClass.class_id).where(DrugClass.source == "ATC")))
    if not epc:
        pytest.skip("classes not loaded")
    flags = set(session.scalars(select(DrugClass.class_id).where(DrugClass.source == "LABEL_FLAG")))
    ings = set(session.scalars(select(Ingredient.name)))
    missing = []
    for group in rules.groups.values():
        for sel in group.selectors:
            known = {"EPC": epc, "ATC": atc, "FLAG": flags, "ING": ings}[sel.kind]
            if sel.value not in known:
                missing.append(f"{group.key}: {sel.kind}:{sel.value}")
    assert missing == []


def test_dolo_and_crocin_duplicate_paracetamol(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Dolo 650", "Crocin")
    assert [f.type for f in r.findings] == ["duplicate_ingredient"]


def test_warfarin_aspirin_ibuprofen(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Warfarin 5mg", "Ecosprin 75", "Brufen 400"
            if normaliser.normalise("Brufen 400").best else "Ibuprofen 400")  # fmt: skip
    severities = {
        (tuple(sorted(f.ingredients)), f.severity) for f in r.findings if f.type == "interaction"
    }
    assert (("ibuprofen", "warfarin"), "major") in severities
    assert (("aspirin", "warfarin"), "major") in severities
    assert any(f.rule_id == "BLEEDING_STACK" for f in r.findings)
    assert r.findings[0].severity in ("contraindicated", "major")


def test_serotonin_and_qt_stack(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Sertraline 50", "Tramadol", "Ondem MD 4")
    # Only sertraline and ondansetron carry QT flags; that 2-drug rule merges into their pair
    # card when one exists, so look at merged rules too.
    assert {"SEROTONIN_STACK", "QT_STACK"} <= rule_ids(r)


def test_two_india_nsaids(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Zerodol-P", "Nise 100")
    text = " ".join([f.title for f in r.findings] + [n for f in r.findings for n in f.related])
    assert "NSAID" in text


def test_contraindicated_pair_from_medrt(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Amiodarone", "Levofloxacin")
    assert r.findings[0].severity == "contraindicated"
    assert {e.dataset for e in r.findings[0].evidence} >= {"ddinter", "medrt"}


def test_triple_whammy(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Ibuprofen 400", "Lisinopril 10", "Furosemide 40")
    assert any(f.rule_id == "KIDNEY_TRIPLE" for f in r.findings)


def test_pregnancy_context(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Ibuprofen 400", ctx=PatientContext(pregnant=True))
    assert any(f.type == "context" for f in r.findings) or r.notes


def test_no_issues_are_reported_as_checked_not_safe(session, normaliser) -> None:  # type: ignore[no-untyped-def]
    r = run(session, normaliser, "Metformin 500", "Amlodipine 5")
    if not r.findings:
        assert r.no_known_issue_pairs and r.checked_pairs == 1
