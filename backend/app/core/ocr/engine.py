"""Pluggable OCR engines. Tesseract is the default: free, local and private (the image never
leaves the server). A vision-LLM engine is optional (see vision_llm.py) and off by default.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.ocr.preprocess import Prepared


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float  # 0-100, mean word confidence (100 when the engine gives none)
    box: tuple[int, int, int, int]  # x, y, w, h in the prepared image


class OcrEngine(Protocol):
    name: str
    sends_image_off_device: bool

    def recognise(self, prepared: Prepared) -> list[OcrLine]: ...


def group_words(data: Mapping[str, Sequence[object]]) -> list[OcrLine]:
    """Turn pytesseract.image_to_data(output_type=DICT) words into lines (pure, testable)."""
    lines: dict[tuple[int, int, int, int], list[int]] = defaultdict(list)
    for i, word in enumerate(data["text"]):
        text = str(word).strip()
        conf = float(str(data["conf"][i]))
        if not text or conf < 0:
            continue
        key = tuple(int(str(data[k][i])) for k in ("page_num", "block_num", "par_num", "line_num"))
        lines[key].append(i)  # type: ignore[index]
    out = []
    for indices in lines.values():
        words = [str(data["text"][i]).strip() for i in indices]
        confs = [float(str(data["conf"][i])) for i in indices]
        lefts = [int(str(data["left"][i])) for i in indices]
        tops = [int(str(data["top"][i])) for i in indices]
        rights = [lefts[j] + int(str(data["width"][i])) for j, i in enumerate(indices)]
        bottoms = [tops[j] + int(str(data["height"][i])) for j, i in enumerate(indices)]
        box = (min(lefts), min(tops), max(rights) - min(lefts), max(bottoms) - min(tops))
        out.append(OcrLine(" ".join(words), round(sum(confs) / len(confs), 1), box))
    out.sort(key=lambda line: (line.box[1], line.box[0]))
    return out


class TesseractEngine:
    name = "tesseract"
    sends_image_off_device = False

    def __init__(self, lang: str = "eng") -> None:
        self.lang = lang

    def recognise(self, prepared: Prepared) -> list[OcrLine]:
        import pytesseract

        # psm 4: a single column of text of variable sizes, which suits prescriptions.
        data = pytesseract.image_to_data(
            prepared.binary,
            lang=self.lang,
            config="--oem 1 --psm 4",
            output_type=pytesseract.Output.DICT,
        )
        return group_words(data)
