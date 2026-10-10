"""Request/response models for /api/v1. Responses mirror the pure core dataclasses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ITEMS = 20
TEXT = Field(min_length=1, max_length=120)


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ requests


class Selection(Model):
    """A candidate the user picked (from /normalise or /drugs/search)."""

    ref: str | None = Field(default=None, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    ingredients: list[str] = Field(min_length=1, max_length=10)

    @field_validator("ingredients")
    @classmethod
    def _rxcuis(cls, value: list[str]) -> list[str]:
        if not all(v.isdigit() and len(v) <= 12 for v in value):
            raise ValueError("ingredients must be RxCUIs (digits)")
        return value


class CheckItem(Model):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = TEXT
    selection: Selection | None = None
    batch: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9 ./_-]*$")


class Context(Model):
    age_group: Literal["child", "adult", "older"] | None = None
    pregnant: bool = False
    renal: bool = False
    hepatic: bool = False


class CheckRequest(Model):
    items: list[CheckItem] = Field(min_length=1, max_length=MAX_ITEMS)
    context: Context = Context()

    @field_validator("items")
    @classmethod
    def _unique_ids(cls, items: list[CheckItem]) -> list[CheckItem]:
        if len({i.id for i in items}) != len(items):
            raise ValueError("item ids must be unique")
        return items


class NormaliseRequest(Model):
    lines: list[str] = Field(min_length=1, max_length=MAX_ITEMS)

    @field_validator("lines")
    @classmethod
    def _line_length(cls, lines: list[str]) -> list[str]:
        if any(not line.strip() or len(line) > 120 for line in lines):
            raise ValueError("each line must be 1-120 characters")
        return lines


# ------------------------------------------------------------------ normalisation


class Strength(Model):
    value: str
    unit: str | None


class Candidate(Model):
    label: str
    kind: str
    ingredients: list[str]
    ingredient_names: list[str]
    confidence: float
    method: str
    ref: str
    source: str


class NormalisedLine(Model):
    raw: str
    query: str
    status: Literal["resolved", "confirm", "unknown"]
    confidence: float
    best: Candidate | None
    candidates: list[Candidate]
    strengths: list[Strength]
    dose_form: str | None


class NormaliseResponse(Model):
    results: list[NormalisedLine]


class SearchHit(Model):
    label: str
    kind: str
    ingredients: list[str]
    ingredient_names: list[str]
    ref: str
    source: str


class SearchResponse(Model):
    query: str
    hits: list[SearchHit]


# ------------------------------------------------------------------ check


class Evidence(Model):
    dataset: str
    dataset_name: str
    dataset_version: str | None
    record_id: str
    url: str | None
    quote: str | None


class Finding(Model):
    id: str
    type: str
    severity: str
    medicines: list[str]
    drug_labels: list[str]
    ingredients: list[str]
    ingredient_ids: list[str]
    title: str
    simple: str
    professional: str
    consider: str
    evidence: list[Evidence]
    provenance: str
    confidence: str
    rule_id: str | None
    related: list[str]
    related_rules: list[str]


class CheckNote(Model):
    context: str
    medicine: str
    ingredient: str
    text: str
    evidence: Evidence


class RecallFlag(Model):
    medicine_id: str
    medicine_label: str
    match: str
    level: str
    region: str
    kind: str
    title: str
    simple: str
    consider: str
    product_description: str
    reason: str | None
    firm: str | None
    status: str | None
    report_date: date | None
    lot_info: str | None
    evidence: Evidence


class IngredientSummary(Model):
    medicine_id: str
    medicine_label: str
    region: str
    total: int
    recent: list[RecallFlag]


class ChecklistItem(Model):
    id: str
    check: str
    why: str
    source: str
    source_url: str | None


class Recalls(Model):
    flags: list[RecallFlag]
    ingredient_summaries: list[IngredientSummary]
    checklist: list[ChecklistItem]
    coverage_notes: list[str]


class Summary(Model):
    headline: str
    needs_attention: int
    worth_checking: int
    other: int
    checked_medicines: int
    unresolved: int


class Ingredient(Model):
    rxcui: str
    name: str


class CheckedMedicine(Model):
    id: str
    text: str
    label: str
    ingredients: list[Ingredient]
    how: str  # resolved | selected
    confidence: float | None
    batch: str | None


class UnresolvedMedicine(Model):
    id: str
    text: str
    status: Literal["confirm", "unknown"]
    candidates: list[Candidate]


class DatasetVersion(Model):
    code: str
    name: str
    version: str | None
    licence: str


class CheckResponse(Model):
    summary: Summary
    medicines: list[CheckedMedicine]
    unresolved: list[UnresolvedMedicine]
    findings: list[Finding]
    notes: list[CheckNote]
    recalls: Recalls
    no_known_issue_pairs: list[list[str]]
    disclaimer: str
    absence_note: str
    data_versions: list[DatasetVersion]


# ------------------------------------------------------------------ datasets


class DatasetInfo(Model):
    code: str
    name: str
    version: str | None
    source_url: str
    licence: str
    licence_url: str | None
    region: str | None
    downloaded_at: datetime | None
    record_count: int | None
    limitations: str | None
    last_ingest_status: str | None
    last_ingest_at: datetime | None


class DatasetsResponse(Model):
    datasets: list[DatasetInfo]
    non_commercial_notice: str


class OfflinePackMeta(Model):
    version: str
    generated_at: str
    download_bytes: int
    raw_bytes: int


# ------------------------------------------------------------------ OCR


class ScannedLine(Model):
    text: str
    ocr_confidence: float
    box: list[int]
    likely_medicine: bool
    status: Literal["resolved", "confirm", "unknown"]
    normalised: NormalisedLine | None
    crop_png_b64: str | None


class ScanResponse(Model):
    engine: str
    sends_image_off_device: bool
    lines: list[ScannedLine]
    warnings: list[str]
    skew_degrees: float
    millis: int
