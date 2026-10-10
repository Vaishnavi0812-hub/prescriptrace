from datetime import date

import pytest

from app.core.engine.templates import FORBIDDEN_PHRASES
from app.core.recalls import CHECKLIST, MedicineRef, RecallRecord, check_recalls
from app.core.recalls.match import normalise_batch


def rec(rid: int, **kw: object) -> RecallRecord:
    base: dict[str, object] = {
        "id": rid, "dataset": "cdsco_alerts", "region": "IN", "source_record_id": f"doc:{rid}",
        "classification": "NSQ", "reason": "Dissolution", "firm": "M/s X", "status": None,
        "report_date": date(2025, 5, 1), "product_description": "Telmisartan Tablets IP 40mg",
        "lot_info": "Batch K18230707; Exp May-2027", "source_url": f"https://x/{rid}.pdf",
    }  # fmt: skip
    base.update(kw)
    return RecallRecord(**base)  # type: ignore[arg-type]


SPURIOUS_TELMA = rec(1, classification="Spurious", ingredients=("TEL",), brands=("Telma 40",))
NSQ_OTHER_BRAND = rec(2, ingredients=("TEL",), brands=("Telsar 40",), lot_info="Batch ABC12345")
US_CLASS3 = rec(3, dataset="openfda_enforcement", region="US", classification="Class III",
                ingredients=("PCM",), product_description="Acetaminophen 500 mg caplets",
                lot_info="Lot 9XY77", report_date=date(2024, 1, 1))  # fmt: skip
US_CLASS1_BRAND = rec(4, dataset="openfda_enforcement", region="US", classification="Class I",
                      ingredients=("PCM",), brands=("TYLENOL EXTRA STRENGTH",),
                      lot_info="Lot 12345ABC")  # fmt: skip
ALL = [SPURIOUS_TELMA, NSQ_OTHER_BRAND, US_CLASS3, US_CLASS1_BRAND]

TELMA = MedicineRef("1", "Telma 40", ("TEL",), ("Telma 40",))


def test_batch_listed_in_alert_is_most_serious() -> None:
    med = MedicineRef("1", "Telma 40", ("TEL",), ("Telma 40",), batch="k18230707")
    result = check_recalls([med], ALL)
    first = result.flags[0]
    assert (first.match, first.level, first.region) == ("batch", "serious", "IN")
    assert first.evidence.url == "https://x/1.pdf"


def test_same_brand_without_batch_is_product_match() -> None:
    result = check_recalls([TELMA], ALL)
    (flag,) = result.flags
    assert (flag.match, flag.level) == ("product", "serious")  # spurious alert
    assert "Only the batches named" in flag.simple


def test_other_brand_with_same_ingredient_is_information_only() -> None:
    result = check_recalls([TELMA], ALL)
    (summary,) = result.ingredient_summaries
    assert (summary.region, summary.total) == ("IN", 1)
    assert summary.recent[0].level == "info"
    assert result.attention_count == 1  # only the spurious same-brand alert


def test_batch_on_a_different_products_alert_still_counts() -> None:
    # The user's batch appears in an alert for another brand of the same medicine.
    med = MedicineRef("1", "Telsar", ("TEL",), ("Telsar",), batch="ABC-12345")
    flags = check_recalls([med], ALL).flags
    assert [f.match for f in flags][:1] == ["batch"]


def test_brand_prefix_rules() -> None:
    tylenol = MedicineRef("2", "Tylenol", ("PCM",), ("Tylenol",))
    flags = check_recalls([tylenol], ALL).flags
    assert [(f.match, f.level, f.region) for f in flags] == [("product", "serious", "US")]
    crocinol = MedicineRef("3", "Tylenolix", ("ZZZ",), ("Tylenolix",))
    assert check_recalls([crocinol], ALL).flags == ()


def test_unrelated_medicine_has_no_flags() -> None:
    result = check_recalls([MedicineRef("9", "Metformin", ("MET",), ("Glycomet",))], ALL)
    assert (result.flags, result.ingredient_summaries) == ((), ())


@pytest.mark.parametrize(("raw", "expected"), [("k18-230 707", "K18230707"), ("A1", None),
                                               (None, None)])  # fmt: skip
def test_batch_normalisation(raw: str | None, expected: str | None) -> None:
    assert normalise_batch(raw) == expected


def test_checklist_items_name_their_source_honestly() -> None:
    assert len(CHECKLIST) >= 5
    for item in CHECKLIST:
        assert item.check and item.why and item.source
        if item.source_url is None:
            assert "general good practice" in item.source.lower()
        else:
            assert item.source_url.startswith(("https://cdsco.gov.in/", "https://www.fda.gov/"))


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_recall_wording_never_tells_anyone_to_stop_a_medicine(phrase: str) -> None:
    med = MedicineRef("1", "Telma 40", ("TEL",), ("Telma 40",), batch="K18230707")
    result = check_recalls([med, TELMA], ALL)
    flags = list(result.flags) + [f for s in result.ingredient_summaries for f in s.recent]
    text = " ".join(f.title + f.simple + f.consider for f in flags)
    text += " ".join(i.check + i.why for i in CHECKLIST)
    assert phrase not in text.lower()
