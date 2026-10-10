"""Interaction engine on a hand-built knowledge snapshot (no database)."""

from dataclasses import replace

import pytest

from app.core.engine import (
    ClassTag,
    ContextFact,
    DatasetMeta,
    InteractionFact,
    KnowledgeSnapshot,
    LabelText,
    Medicine,
    PatientContext,
    check,
    load_rules,
)
from app.core.engine.model import SEVERITY_RANK
from app.core.engine.templates import FORBIDDEN_PHRASES

N = {
    "W": "warfarin",
    "IB": "ibuprofen",
    "AS": "aspirin",
    "CL": "clopidogrel",
    "PCM": "acetaminophen",
    "ACE": "aceclofenac",
    "SER": "sertraline",
    "TRA": "tramadol",
    "OND": "ondansetron",
    "AZI": "azithromycin",
    "LIS": "lisinopril",
    "FUR": "furosemide",
    "SPI": "spironolactone",
    "TEL": "telmisartan",
    "AMI": "amiodarone",
    "LEV": "levofloxacin",
    "MET": "metformin",
    "DIA": "diazepam",
    "MOR": "morphine",
}


def epc(name: str) -> ClassTag:
    return ClassTag("EPC", f"N{abs(hash(name)) % 10**6}", name, "rxclass_fdaspl")


def atc(code: str) -> ClassTag:
    return ClassTag("ATC", code, code, "atc")


def flag(name: str, status: str = "auto") -> ClassTag:
    return ClassTag(
        "LABEL_FLAG",
        name,
        name,
        "openfda_label",
        status,
        f"set_id=abc-{name}; warnings: ... {name} warning text ...",
    )


CLASSES = {
    "W": [epc("Vitamin K Antagonist"), atc("B01AA")],
    "IB": [epc("Nonsteroidal Anti-inflammatory Drug"), atc("M01AE")],
    "ACE": [atc("M01AB")],  # India-only NSAID: no FDA class, ATC only
    "AS": [epc("Platelet Aggregation Inhibitor"), atc("B01AC"), atc("N02AJ")],  # N02AJ trap
    "CL": [epc("P2Y12 Platelet Inhibitor"), atc("B01AC")],
    "SER": [epc("Serotonin Reuptake Inhibitor"), flag("serotonergic"), flag("qt_prolonging")],
    "TRA": [flag("serotonergic"), flag("cns_depressant"), atc("N02AX")],
    "OND": [flag("qt_prolonging"), flag("serotonergic")],
    "AZI": [flag("qt_prolonging"), epc("Macrolide Antimicrobial")],
    "MET": [flag("qt_prolonging", "rejected")],  # a rejected flag must never count
    "LIS": [epc("Angiotensin Converting Enzyme Inhibitor")],
    "TEL": [epc("Angiotensin 2 Receptor Blocker")],
    "FUR": [epc("Loop Diuretic")],
    "SPI": [epc("Aldosterone Antagonist")],
    "DIA": [epc("Benzodiazepine"), flag("cns_depressant")],
    "MOR": [epc("Opioid Agonist"), flag("cns_depressant")],
}


def fact(a: str, b: str, sev: str, ds: str = "ddinter") -> InteractionFact:
    return InteractionFact(a, b, sev, "structured", ds, f"{ds}:{a}-{b}", f"https://x/{a}")


KB = KnowledgeSnapshot(
    names=N,
    interactions=[
        fact("W", "IB", "major"),
        fact("W", "AS", "major"),
        fact("W", "PCM", "moderate"),
        fact("SER", "TRA", "major"),
        fact("AMI", "LEV", "major"),
        fact("AMI", "LEV", "contraindicated", "medrt"),
        fact("LIS", "SPI", "major"),
        fact("IB", "ACE", "unknown"),
    ],
    classes=CLASSES,
    context=[
        ContextFact(
            "IB",
            "pregnancy",
            "contraindication",
            "Listed as contraindicated in: Pregnancy Trimester, Third",
            "medrt",
            "CI 1",
        ),
        ContextFact(
            "IB",
            "pregnancy",
            "check_label",
            "8.1 Pregnancy Risk Summary ...",
            "openfda_label",
            "set_id=lbl-ib",
        ),
        ContextFact(
            "MET",
            "renal",
            "check_label",
            "8.6 Renal Impairment ...",
            "openfda_label",
            "set_id=lbl-met",
        ),
    ],
    labels={
        "SER": LabelText(
            "SER",
            "lbl-ser",
            "Zoloft",
            "Drugs that interfere with hemostasis (e.g., warfarin, NSAIDs): "
            "concomitant use may increase bleeding risk.",
        ),
    },
    datasets={
        "ddinter": DatasetMeta("ddinter", "DDInter 2.0", "2.0", "CC BY-NC-SA 4.0"),
        "medrt": DatasetMeta("medrt", "MED-RT", None, "TBC"),
    },
)

m = Medicine


def run(*meds: Medicine, ctx: PatientContext | None = None):  # type: ignore[no-untyped-def]
    return check(list(meds), KB, ctx)


def by_type(result, ftype):  # type: ignore[no-untyped-def]
    return [f for f in result.findings if f.type == ftype]


# ------------------------------------------------------------------ pairwise


def test_pairwise_major_with_source() -> None:
    r = run(m("1", "Warfarin 5", ("W",)), m("2", "Brufen 400", ("IB",)))
    (f,) = r.findings
    assert (f.type, f.severity, f.provenance, f.confidence) == (
        "interaction",
        "major",
        "structured",
        "high",
    )
    assert f.evidence[0].dataset == "ddinter" and f.evidence[0].record_id == "ddinter:W-IB"
    assert "Consider confirming with the prescriber" in f.consider


def test_most_severe_source_wins_and_all_sources_are_cited() -> None:
    r = run(m("1", "Amiodarone", ("AMI",)), m("2", "Levofloxacin", ("LEV",)))
    (f,) = r.findings
    assert f.severity == "contraindicated"
    assert {e.dataset for e in f.evidence} == {"ddinter", "medrt"}


def test_combination_product_checks_each_ingredient() -> None:
    r = run(m("1", "Warfarin", ("W",)), m("2", "Combiflam", ("IB", "PCM")))
    assert sorted(f.severity for f in by_type(r, "interaction")) == ["major", "moderate"]


def test_ingredients_inside_one_product_are_not_paired() -> None:
    assert run(m("1", "Combiflam", ("IB", "PCM"))).findings == ()


def test_label_mention_is_added_as_quoted_evidence() -> None:
    r = run(m("1", "Sertraline", ("SER",)), m("2", "Warfarin", ("W",)))
    (f,) = by_type(r, "interaction")
    assert (f.severity, f.provenance, f.confidence) == ("unknown", "label_text", "low")
    assert f.evidence[0].quote and "warfarin" in f.evidence[0].quote
    assert f.evidence[0].url and "dailymed" in f.evidence[0].url


def test_quiet_pairs_are_reported_as_checked_without_findings() -> None:
    r = run(m("1", "Metformin", ("MET",)), m("2", "Telma 40", ("TEL",)))
    assert r.findings == ()
    assert r.no_known_issue_pairs == (("Metformin", "Telma 40"),)


# ------------------------------------------------------------------ duplicates


def test_same_ingredient_in_two_brands() -> None:
    r = run(m("1", "Crocin", ("PCM",)), m("2", "Dolo 650", ("PCM",)))
    (f,) = r.findings
    assert (f.type, f.severity, f.rule_id) == ("duplicate_ingredient", "major", "DUP_INGREDIENT")
    assert "Crocin and Dolo 650" in f.simple


def test_two_nsaids_including_atc_only_drug() -> None:
    r = run(m("1", "Brufen", ("IB",)), m("2", "Zerodol", ("ACE",)))
    # The unknown-severity DDInter pair absorbs the duplicate-class note (one card, not two).
    (f,) = r.findings
    assert f.type == "interaction"
    assert f.severity == "major"  # raised by the merged NSAID-duplication rule
    assert any("NSAID" in note for note in f.related)


def test_two_nsaids_without_pair_data_get_their_own_card() -> None:
    kb = replace(KB, interactions=[])
    r = check([m("1", "Brufen", ("IB",)), m("2", "Zerodol", ("ACE",))], kb)
    (f,) = r.findings
    assert (f.type, f.rule_id, f.severity) == ("duplicate_class", "DUP_CLASS", "major")
    assert {e.dataset for e in f.evidence} >= {"rxclass_fdaspl", "atc", "rules"}


# ------------------------------------------------------------------ cumulative


def test_three_qt_drugs_make_a_cumulative_card() -> None:
    r = run(m("1", "Sertraline", ("SER",)), m("2", "Ondem", ("OND",)), m("3", "Azee", ("AZI",)))
    (qt,) = [f for f in r.findings if f.rule_id == "QT_STACK"]
    assert (qt.type, qt.severity, qt.confidence) == ("cumulative", "major", "medium")
    assert set(qt.ingredients) == {"sertraline", "ondansetron", "azithromycin"}
    assert sum(1 for e in qt.evidence if e.dataset == "openfda_label") == 3


def test_rejected_flag_never_counts() -> None:
    r = run(m("1", "Azee", ("AZI",)), m("2", "Metformin", ("MET",)))
    assert not [f for f in r.findings if f.rule_id == "QT_STACK"]


def test_two_drug_rule_merges_into_existing_pair_card() -> None:
    r = run(m("1", "Sertraline", ("SER",)), m("2", "Tramadol", ("TRA",)))
    (f,) = r.findings
    assert f.type == "interaction" and f.severity == "major"
    assert any("serotonin" in note.lower() for note in f.related)


def test_bleeding_stack_needs_three_drugs_from_two_groups() -> None:
    two = run(m("1", "Ecosprin", ("AS",)), m("2", "Clopilet", ("CL",)))
    assert not [f for f in two.findings if f.rule_id == "BLEEDING_STACK"]
    three = run(m("1", "Ecosprin", ("AS",)), m("2", "Clopilet", ("CL",)), m("3", "Brufen", ("IB",)))
    (f,) = [f for f in three.findings if f.rule_id == "BLEEDING_STACK"]
    assert set(f.ingredients) == {"aspirin", "clopidogrel", "ibuprofen"}


def test_aspirin_is_not_an_opioid_despite_atc_n02aj() -> None:
    r = run(m("1", "Ecosprin", ("AS",)), m("2", "Morphine", ("MOR",)))
    assert not [f for f in r.findings if f.rule_id in ("SEDATION_STACK",)]
    assert not [f for f in r.findings if f.type == "duplicate_class"]


def test_sedation_stack_benzo_plus_opioid() -> None:
    r = run(m("1", "Valium", ("DIA",)), m("2", "Morphine", ("MOR",)))
    (f,) = r.findings
    assert (f.rule_id, f.severity) == ("SEDATION_STACK", "major")


def test_kidney_triple_requires_all_three_roles() -> None:
    no_diuretic = run(
        m("1", "Brufen", ("IB",)), m("2", "Lisinopril", ("LIS",)), m("3", "Telma", ("TEL",))
    )
    assert not [f for f in no_diuretic.findings if f.rule_id == "KIDNEY_TRIPLE"]
    triple = run(
        m("1", "Brufen", ("IB",)), m("2", "Lisinopril", ("LIS",)), m("3", "Lasix", ("FUR",))
    )
    assert [f for f in triple.findings if f.rule_id == "KIDNEY_TRIPLE"]


def test_potassium_rule_merges_with_known_pair() -> None:
    r = run(m("1", "Lisinopril", ("LIS",)), m("2", "Aldactone", ("SPI",)))
    (f,) = r.findings
    assert f.type == "interaction" and any("potassium" in n.lower() for n in f.related)


# ------------------------------------------------------------------ patient context


def test_context_only_when_selected() -> None:
    meds = (m("1", "Brufen", ("IB",)),)
    assert run(*meds).findings == () and run(*meds).notes == ()
    r = run(*meds, ctx=PatientContext(pregnant=True))
    (f,) = r.findings
    assert (f.type, f.severity, f.evidence[0].dataset) == ("context", "contraindicated", "medrt")
    (note,) = r.notes
    assert note.context == "pregnancy" and note.evidence.url and "lbl-ib" in note.evidence.url


def test_check_label_note_for_kidney_impairment() -> None:
    r = run(m("1", "Glycomet", ("MET",)), ctx=PatientContext(renal=True))
    assert r.findings == ()
    assert [n.ingredient for n in r.notes] == ["metformin"]


# ------------------------------------------------------------------ whole-result properties


def test_ranking_most_severe_first() -> None:
    r = run(
        m("1", "Warfarin", ("W",)),
        m("2", "Combiflam", ("IB", "PCM")),
        m("3", "Amiodarone", ("AMI",)),
        m("4", "Levoflox", ("LEV",)),
    )
    ranks = [SEVERITY_RANK[f.severity] for f in r.findings]
    assert ranks == sorted(ranks)
    assert r.findings[0].severity == "contraindicated"
    assert r.attention_count == len(r.findings)


def test_every_finding_has_evidence_and_consider_text() -> None:
    meds = [m(str(i), N[k], (k,)) for i, k in enumerate(N)]
    r = check(meds, KB, PatientContext(pregnant=True, renal=True))
    assert r.findings
    for f in r.findings:
        assert f.evidence, f.id
        assert f.consider and f.simple and f.title


def test_deterministic_and_independent_of_list_order() -> None:
    meds = [m(str(i), N[k], (k,)) for i, k in enumerate(N)]

    def summary(result):  # type: ignore[no-untyped-def]
        return sorted(
            (f.type, f.severity, tuple(sorted(f.ingredients)), f.rule_id or "")
            for f in result.findings
        )

    assert check(meds, KB) == check(meds, KB)
    assert summary(check(meds, KB)) == summary(check(list(reversed(meds)), KB))


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_no_output_text_tells_anyone_to_stop_or_change_therapy(phrase: str) -> None:
    from app.core.engine import templates

    rules = load_rules()
    texts = [rules.dup_ingredient_text, rules.dup_class_text, *(r.text for r in rules.cumulative)]
    corpus = " ".join(
        [v for t in texts for v in (t.title, t.simple, t.professional, t.consider)]
        + [str(v) for k, v in vars(templates).items() if k.isupper() and k != "FORBIDDEN_PHRASES"]
    ).lower()
    assert phrase not in corpus
