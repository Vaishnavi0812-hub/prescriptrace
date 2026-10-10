"""Choose the OCR engine from settings. Tesseract unless OCR_ENGINE=vision_llm is configured."""

from __future__ import annotations

from app.config import get_settings
from app.core.ocr import OcrEngine, TesseractEngine


class OcrUnavailableError(RuntimeError):
    pass


def get_engine() -> OcrEngine:
    settings = get_settings()
    if settings.ocr_engine == "tesseract":
        return TesseractEngine()
    if settings.ocr_engine == "vision_llm":
        from app.core.ocr.vision_llm import VisionLLMEngine

        return VisionLLMEngine.from_settings(settings)
    raise OcrUnavailableError(f"unknown OCR_ENGINE {settings.ocr_engine!r}")
