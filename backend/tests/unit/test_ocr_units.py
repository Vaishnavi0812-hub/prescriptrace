"""OCR building blocks that need no Tesseract and no database."""

import pytest

from app.core.ocr import ImageError, decode, group_words, prepare
from app.core.ocr.preprocess import estimate_skew
from app.core.ocr.synthetic import render


def test_group_words_into_lines_in_reading_order() -> None:
    data = {
        "text": ["Tab.", "Dolo", "650", "", "Cap", "Omez"],
        "conf": [91, 88, 95, -1, 70, 80],
        "page_num": [1] * 6, "block_num": [1] * 6, "par_num": [1] * 6,
        "line_num": [2, 2, 2, 2, 1, 1],
        "left": [10, 60, 140, 0, 10, 60], "top": [50, 52, 51, 0, 10, 11],
        "width": [40, 70, 50, 0, 40, 60], "height": [20, 20, 20, 0, 20, 20],
    }  # fmt: skip
    lines = group_words(data)
    assert [line.text for line in lines] == ["Cap Omez", "Tab. Dolo 650"]
    assert lines[1].box == (10, 50, 180, 22)
    assert lines[1].confidence == pytest.approx(91.3, abs=0.1)


@pytest.mark.parametrize("angle", [-6.0, -2.5, 3.0, 7.0])
def test_skew_is_estimated_and_corrected(angle: float) -> None:
    image = decode(render(["Tab Dolo 650", "Cap Omez 20", "Tab Telma 40"], rotate=angle))
    from cv2 import COLOR_BGR2GRAY, cvtColor

    gray = cvtColor(image, COLOR_BGR2GRAY)
    # The estimate is the correction: the opposite of the tilt that was applied.
    assert estimate_skew(gray) == pytest.approx(-angle, abs=1.0)
    prepared = prepare(image)
    assert prepared.skew_degrees == pytest.approx(-angle, abs=1.0)
    assert estimate_skew(prepared.gray) == pytest.approx(0.0, abs=0.5)  # level after correction


def test_small_photos_are_upscaled() -> None:
    prepared = prepare(decode(render(["Tab Dolo 650"], width=600, font_size=16)))
    assert prepared.scale > 2.5
    assert prepared.binary.shape[1] >= 1700


def test_non_images_are_rejected() -> None:
    with pytest.raises(ImageError):
        decode(b"%PDF-1.7 not an image")
    with pytest.raises(ImageError):
        decode(b"")
