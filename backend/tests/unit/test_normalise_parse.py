import pytest

from app.core.normalise.parse import Strength, ocr_variants, parse


@pytest.mark.parametrize(
    ("raw", "full", "core"),
    [
        ("Crocin 650", "crocin 650", "crocin"),
        ("Augmentin 625 Duo", "augmentin 625 duo", "augmentin duo"),
        ("paracetamol 650 mg tab", "paracetamol 650 mg", "paracetamol"),
        ("Tab. Dolo 650 1-0-1 x 5 days", "dolo 650", "dolo"),
        ("2) Syp Calpol 5 ml TDS after food", "calpol 5 ml", "calpol"),
        ("Glycomet SR 500", "glycomet sr 500", "glycomet"),
        ("Rx: Pan 40 OD", "pan 40", "pan"),
        # Found by the OCR evaluation: trailing instructions blocked the match.
        ("Tab Thyronorm 50 1-0-0 empty stomach", "thyronorm 50", "thyronorm"),
        ("Tab Atorva 10 at bedtime", "atorva 10", "atorva"),
        ("Cap Omez 20 before breakfast", "omez 20", "omez"),
    ],
)
def test_parse_full_and_core(raw: str, full: str, core: str) -> None:
    parsed = parse(raw)
    assert parsed.full == full
    assert parsed.core == core


def test_strengths_and_dose_form() -> None:
    parsed = parse("Ecosprin AV 75/40 cap")
    assert parsed.strengths == (Strength("75/40", None),)
    assert parsed.dose_form == "capsule"
    assert parse("Thyronorm 50mcg").strengths == (Strength("50", "mcg"),)
    assert parse("Amoxicillin 1 gm").strengths == (Strength("1", "g"),)


@pytest.mark.parametrize(
    ("raw", "components"),
    [
        ("amox/clav", ("amox", "clav")),
        ("amox/clav 625", ("amox", "clav")),
        ("Paracetamol + Ibuprofen", ("paracetamol", "ibuprofen")),
        ("aceclofenac and paracetamol tab", ("aceclofenac", "paracetamol")),
        ("Ecosprin AV 75/40", ()),  # numeric slash is a strength, not a combination
        ("Telma 40", ()),
    ],
)
def test_combination_components(raw: str, components: tuple[str, ...]) -> None:
    assert parse(raw).components == components


def test_ocr_variants_only_touch_digits_between_letters() -> None:
    assert ocr_variants("metf0rmin") == ["metformin"]
    assert set(ocr_variants("amoxici11in")) >= {"amoxicillin"}
    assert ocr_variants("dolo 650") == []  # a real strength is left alone
