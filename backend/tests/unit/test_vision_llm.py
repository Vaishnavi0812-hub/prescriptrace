"""The optional vision-LLM adapter, with a fake client (no network, no cost)."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.normalise import Entry, Normaliser, Vocabulary
from app.core.ocr import scan
from app.core.ocr.synthetic import render
from app.core.ocr.vision_llm import VisionLLMEngine, VisionUnavailableError


class FakeMessages:
    def __init__(self, payload: dict[str, Any], stop_reason: str = "end_turn") -> None:
        self.payload = payload
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.payload))
        return SimpleNamespace(stop_reason=self.stop_reason, content=[block])


def engine(
    payload: dict[str, Any], stop_reason: str = "end_turn"
) -> tuple[VisionLLMEngine, FakeMessages]:
    messages = FakeMessages(payload, stop_reason)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return VisionLLMEngine(client), messages


VOCAB = Vocabulary(
    {"161": "acetaminophen"},
    [Entry("Dolo 650", "dolo 650", "india_brand", ("161",), "india_brand:1", "t")],
)


def test_lines_are_never_auto_accepted_and_have_no_crops() -> None:
    eng, messages = engine(
        {
            "lines": [
                {"text": "Tab Dolo 650 1-0-1", "illegible": False},
                {"text": "Patient: Test Person", "illegible": False},
            ]
        }
    )
    result = scan(render(["Tab Dolo 650"]), eng, Normaliser(VOCAB))
    assert result.sends_image_off_device is True
    med = next(line for line in result.lines if line.likely_medicine)
    assert med.normalised is not None and med.normalised.best is not None
    assert med.status == "confirm"  # even a perfect name match needs the user's confirmation
    assert med.crop_png_b64 is None
    request = messages.calls[0]
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["fallbacks"] == "default"


def test_refusal_is_reported_not_guessed() -> None:
    eng, _ = engine({"lines": []}, stop_reason="refusal")
    with pytest.raises(VisionUnavailableError):
        scan(render(["Tab Dolo 650"]), eng, Normaliser(VOCAB))


def test_not_configured_means_unavailable() -> None:
    settings = SimpleNamespace(llm_provider="none", llm_api_key="", llm_model="")
    with pytest.raises(VisionUnavailableError):
        VisionLLMEngine.from_settings(settings)
