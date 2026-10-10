from app.ingest.label_rules import context_excerpts, find_flags, sentences


def flags(**sections: str) -> dict[str, bool]:
    return {h.flag: h.needs_review for h in find_flags(sections)}


def test_qt_flag_from_warnings() -> None:
    text = "5.3 QT Prolongation Ondansetron prolongs the QT interval in a dose-dependent manner."
    assert flags(warnings_and_cautions=text) == {"qt_prolonging": False}


def test_qt_flag_from_torsade_mention() -> None:
    assert "qt_prolonging" in flags(boxed_warning="Cases of torsade de pointes were reported.")


def test_negated_qt_statement_needs_review() -> None:
    text = "In a thorough QT study, drug X did not prolong the QTc interval."
    assert flags(warnings_and_cautions=text) == {"qt_prolonging": True}


def test_affirmative_sentence_wins_over_negated_one() -> None:
    text = (
        "A study showed no effect on QT prolongation at therapeutic doses. "
        "At supratherapeutic doses the drug prolongs the QT interval."
    )
    assert flags(warnings=text) == {"qt_prolonging": False}


def test_serotonin_and_cns_flags() -> None:
    boxed = (
        "Concomitant use with benzodiazepines or other CNS depressants may result in profound "
        "sedation, respiratory depression, coma, and death."
    )
    warn = "Serotonin syndrome has been reported with SSRIs."
    assert flags(boxed_warning=boxed, warnings_and_cautions=warn) == {
        "cns_depressant": False,
        "serotonergic": False,
    }


def test_interaction_section_is_not_used_for_flags() -> None:
    # Linezolid's partners cause serotonin syndrome; that is an interaction, not a class.
    assert flags(drug_interactions="Serotonin syndrome has occurred with SSRIs.") == {}


def test_context_excerpts_quote_label_text() -> None:
    out = context_excerpts(
        {
            "pregnancy": "8.1 Pregnancy Risk Summary Available data have not identified a risk.",
            "use_in_specific_populations": (
                "8.6 Renal Impairment No dose adjustment is needed. "
                "Use with caution in patients with severe renal impairment. "
                "8.7 Hepatic Impairment Reduce the dose in hepatic impairment."
            ),
        }
    )
    assert out["pregnancy"].startswith("8.1 Pregnancy Risk Summary")
    assert "severe renal impairment" in out["renal"]
    assert "hepatic impairment" in out["hepatic"].lower()
    assert "paediatric" not in out


def test_sentence_split_keeps_decimal_numbers() -> None:
    assert sentences("Take 2.5 mg daily. Then stop.") == ["Take 2.5 mg daily.", "Then stop."]


def test_not_recommended_with_qt_drugs_is_not_a_negation() -> None:
    text = "QTc prolongation: Not recommended in combination with other drugs that prolong QTc."
    assert flags(warnings_and_cautions=text) == {"qt_prolonging": False}


def test_differential_diagnosis_mention_needs_review() -> None:
    text = (
        "Other important considerations in the differential diagnosis include central "
        "anticholinergic toxicity, heat stroke and serotonin syndrome"
    )
    assert flags(warnings=text) == {"serotonergic": True}


def test_evidence_is_centred_on_the_match_in_run_on_text() -> None:
    filler = "word " * 200
    text = filler + "Serotonin syndrome has been reported with this drug " + filler
    (hit,) = find_flags({"warnings": text})
    assert "Serotonin syndrome has been reported" in hit.sentence
    assert hit.sentence.startswith("… ")
