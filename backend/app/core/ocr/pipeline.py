"""Photo of a prescription → candidate medicine lines, each with a crop and a match status.

Safety rules: OCR (especially of handwriting) is often wrong, so
  * a line is "resolved" only if BOTH the OCR confidence and the name match are high;
  * nothing is ever added to the medicine list automatically (the UI asks per line);
  * the image is processed in memory and never stored.
"""

from __future__ import annotations

import base64
import re
import statistics
import time
from dataclasses import dataclass, replace

from app.core.normalise import NormalisedLine, Normaliser
from app.core.ocr.engine import OcrEngine, OcrLine
from app.core.ocr.preprocess import crop_png, decode, prepare

OCR_MIN_CONFIDENCE = 75.0  # below this, a perfect name match still needs confirming
LOW_CONTRAST = 25.0
HANDWRITING_HINT = 60.0  # median line confidence below this: likely handwriting or blur

# Prescription lines that start like a medicine order: "Tab.", "Cap", "Syp", "Inj", "1)", "Rx".
_MED_PREFIX = re.compile(
    r"^\s*(?:\d{1,2}\s*[.)]\s*)?(?:rx\.?\s*)?(tab|cap|syp|syr|inj|susp|oint|drops?)\b", re.I
)
# Numbered list items ("1.", "2)") on a prescription are almost always medicine orders.
_NUMBERED = re.compile(r"^\s*\d{1,2}\s*[.)]\s*[A-Za-z]")
# Lines about the patient, prescriber or clinic: never treated as medicines, and never cropped.
_HEADER = re.compile(
    r"\b(dr\.?|doctor|reg(?:istration)?\.?\s*no|mbbs|md\b|clinic|hospital|phone|mobile|tel|"
    r"address|patient|name|age|sex|gender|date|diagnosis|signature|follow[- ]?up|advice)\b",
    re.I,
)
_PHONE = re.compile(r"\d[\d\s-]{8,}\d")


@dataclass(frozen=True)
class ScannedLine:
    text: str
    ocr_confidence: float
    box: tuple[int, int, int, int]
    likely_medicine: bool
    status: str  # resolved | confirm | unknown
    normalised: NormalisedLine | None
    crop_png_b64: str | None


@dataclass(frozen=True)
class ScanResult:
    engine: str
    sends_image_off_device: bool
    lines: tuple[ScannedLine, ...]
    warnings: tuple[str, ...]
    skew_degrees: float
    millis: int


def scan(data: bytes, engine: OcrEngine, normaliser: Normaliser) -> ScanResult:
    started = time.perf_counter()
    prepared = prepare(decode(data))
    raw_lines = [line for line in engine.recognise(prepared) if line.text.strip()]
    lines = tuple(_classify(line, normaliser, prepared.gray) for line in raw_lines)

    warnings = []
    if not raw_lines:
        warnings.append("no_text")
    if prepared.contrast < LOW_CONTRAST:
        warnings.append("low_contrast")
    confidences = [line.confidence for line in raw_lines]
    if confidences and statistics.median(confidences) < HANDWRITING_HINT:
        warnings.append("handwriting_or_blur")
    if raw_lines and not any(line.likely_medicine for line in lines):
        warnings.append("no_medicines_found")
    return ScanResult(
        engine=engine.name,
        sends_image_off_device=engine.sends_image_off_device,
        lines=lines,
        warnings=tuple(warnings),
        skew_degrees=prepared.skew_degrees,
        millis=int((time.perf_counter() - started) * 1000),
    )


def _classify(line: OcrLine, normaliser: Normaliser, gray: object) -> ScannedLine:
    text = " ".join(line.text.split())
    header = bool(_HEADER.search(text) or _PHONE.search(text))
    normalised = None if header else normaliser.normalise(text)
    # A medicine line either looks like an order ("Tab …", "2) …") or fully resolves to a
    # medicine. A weak match on an ordinary line ("Review after 1 week" → "After-bug") is not
    # enough; such lines stay under "other text", where the user can still add them.
    ordered = bool(_MED_PREFIX.match(text) or _NUMBERED.match(text))
    resolved = normalised is not None and normalised.status == "resolved"
    likely = not header and (ordered or resolved)

    status = "unknown"
    if normalised is not None and likely:
        status = normalised.status
        if status == "resolved" and line.confidence < OCR_MIN_CONFIDENCE:
            # The name matched, but the OCR itself was unsure: never auto-accept.
            status = "confirm"
            normalised = replace(normalised, status="confirm")
        if len(normalised.query.replace(" ", "")) < 4 and status == "resolved":
            status = "confirm"  # "Pan", "mg" … too short to trust from OCR
            normalised = replace(normalised, status="confirm")
    crop = None
    if likely and line.box[2] > 0 and line.box[3] > 0:  # engines without positions: no crop
        crop = base64.b64encode(crop_png(gray, line.box)).decode("ascii")  # type: ignore[arg-type]
    return ScannedLine(text, line.confidence, line.box, likely, status, normalised, crop)
