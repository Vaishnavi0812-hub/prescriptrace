"""Prescription OCR: image clean-up, pluggable OCR engines, candidate medicine lines."""

from app.core.ocr.engine import OcrEngine, OcrLine, TesseractEngine, group_words
from app.core.ocr.pipeline import ScannedLine, ScanResult, scan
from app.core.ocr.preprocess import ImageError, Prepared, decode, prepare

__all__ = [
    "ImageError",
    "OcrEngine",
    "OcrLine",
    "Prepared",
    "ScanResult",
    "ScannedLine",
    "TesseractEngine",
    "decode",
    "group_words",
    "prepare",
    "scan",
]
