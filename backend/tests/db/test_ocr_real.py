"""OCR end to end with real Tesseract and the real vocabulary (synthetic prescriptions)."""

import shutil

import pytest

from app.core.normalise import Normaliser
from app.core.ocr import ScanResult, TesseractEngine, scan
from app.core.ocr.synthetic import render
from app.db import _session_factory
from app.repo.vocabulary import load_vocabulary

pytestmark = [
    pytest.mark.db,
    pytest.mark.usefixtures("require_db"),
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
]

MEDS = ["Tab. Dolo 650  1-0-1 x 5 days", "Cap. Omez 20 mg OD", "Tab Augmentin 625 Duo BD",
        "Tab. Telma 40 OD"]  # fmt: skip
EXPECTED = [{"acetaminophen"}, {"omeprazole"}, {"amoxicillin", "clavulanate"}, {"telmisartan"}]


@pytest.fixture(scope="module")
def normaliser() -> Normaliser:
    session = _session_factory()()
    try:
        vocab = load_vocabulary(session)
    finally:
        session.close()
    if len(vocab.entries) < 1000:
        pytest.skip("vocabulary not loaded")
    return Normaliser(vocab)


def medicines(result: ScanResult) -> list[set[str]]:
    return [
        set(line.normalised.best.ingredient_names)
        for line in result.lines
        if line.likely_medicine and line.normalised and line.normalised.best
    ]


@pytest.mark.parametrize(
    "variant",
    [{}, {"rotate": 4.0}, {"rotate": -3.0, "noise": 0.01}, {"serif": True},
     {"width": 700, "font_size": 18}],
    ids=["clean", "rotated", "rotated+noise", "serif", "small-photo"],
)  # fmt: skip
def test_printed_prescription_lines_are_recognised(normaliser: Normaliser, variant: dict) -> None:  # type: ignore[type-arg]
    result = scan(render(MEDS, **variant), TesseractEngine(), normaliser)
    assert medicines(result) == EXPECTED, [line.text for line in result.lines]


def test_header_lines_are_not_medicines_and_are_not_cropped(normaliser: Normaliser) -> None:
    result = scan(render(MEDS), TesseractEngine(), normaliser)
    headers = [line for line in result.lines if not line.likely_medicine]
    assert any("Patient" in line.text for line in headers)
    assert all(line.crop_png_b64 is None for line in headers)
    assert all(line.crop_png_b64 for line in result.lines if line.likely_medicine)


def test_blurry_scan_is_never_auto_accepted(normaliser: Normaliser) -> None:
    result = scan(render(MEDS, blur=2.2, width=800, font_size=20), TesseractEngine(), normaliser)
    for line in result.lines:
        if line.ocr_confidence < 75:
            assert line.status != "resolved", line


def test_blank_page_warns(normaliser: Normaliser) -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (800, 600), 250).save(buf, format="PNG")
    result = scan(buf.getvalue(), TesseractEngine(), normaliser)
    assert "no_text" in result.warnings


def test_footer_text_is_not_a_medicine_line(normaliser: Normaliser) -> None:
    # "Review after 1 week" weakly matches "After-bug"; it must not become a medicine candidate.
    result = scan(render(MEDS), TesseractEngine(), normaliser)
    review = [line for line in result.lines if "Review" in line.text]
    assert review and not review[0].likely_medicine and review[0].crop_png_b64 is None
