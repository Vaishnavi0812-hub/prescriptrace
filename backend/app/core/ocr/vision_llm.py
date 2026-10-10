"""Optional vision-LLM OCR engine (Claude). OFF by default: set OCR_ENGINE=vision_llm,
LLM_PROVIDER=anthropic and LLM_API_KEY, and install the extra: pip install -e ".[llm]".

Trade-off (docs/DECISIONS.md): usually better on handwriting than Tesseract, but it costs money
per image and SENDS THE PRESCRIPTION IMAGE OFF THE DEVICE to Anthropic. The API response says
so (`sends_image_off_device: true`) so the UI can tell the user.

Safety: the model only transcribes text. Its lines go through the same normaliser, and because
an LLM gives no reliable per-line confidence, every line is reported below the auto-accept
threshold: the user must confirm each one. No line positions are returned, so there are no crops.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

import cv2

from app.core.ocr.engine import OcrLine
from app.core.ocr.preprocess import Prepared

MODEL = "claude-opus-5-5"
UNCONFIRMED = 60.0  # below OCR_MIN_CONFIDENCE in pipeline.py: never auto-accepted
MAX_SIDE = 1600  # downscale before upload (cost, privacy: send no more detail than needed)
PROMPT = (
    "Transcribe this prescription image line by line, exactly as written, top to bottom. "
    "Do not correct spellings, expand abbreviations, or add medicines that are not visible. "
    "If a word is illegible, write your best reading and set illegible to true for that line."
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "illegible": {"type": "boolean"},
                },
                "required": ["text", "illegible"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


class VisionUnavailableError(RuntimeError):
    pass


class _Client(Protocol):
    beta: Any


class VisionLLMEngine:
    name = "vision_llm"
    sends_image_off_device = True

    def __init__(self, client: _Client, model: str = MODEL) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_settings(cls, settings: Any) -> VisionLLMEngine:
        if settings.llm_provider != "anthropic" or not settings.llm_api_key:
            raise VisionUnavailableError(
                "OCR_ENGINE=vision_llm needs LLM_PROVIDER=anthropic and LLM_API_KEY"
            )
        try:
            import anthropic
        except ImportError as exc:  # optional dependency
            raise VisionUnavailableError('install the extra: pip install -e ".[llm]"') from exc
        client = anthropic.Anthropic(api_key=settings.llm_api_key)
        return cls(client, settings.llm_model or MODEL)

    def recognise(self, prepared: Prepared) -> list[OcrLine]:
        image = _png_b64(prepared)
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # on a safety decline, re-run on Anthropic's recommended model
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": image},
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
        if response.stop_reason == "refusal":
            raise VisionUnavailableError("the vision model declined this image")
        text = next(block.text for block in response.content if block.type == "text")
        lines = json.loads(text)["lines"]
        return [
            OcrLine(str(line["text"]).strip(), UNCONFIRMED, (0, 0, 0, 0))
            for line in lines
            if str(line["text"]).strip()
        ]


def _png_b64(prepared: Prepared) -> str:
    gray = prepared.gray
    scale = MAX_SIDE / max(gray.shape[:2])
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".png", gray)
    if not ok:
        raise VisionUnavailableError("could not encode image")
    return base64.b64encode(bytes(buffer)).decode("ascii")
