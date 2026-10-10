"""Plain data types for the interaction engine (no database, no web)."""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_ORDER = ("contraindicated", "major", "moderate", "minor", "unknown")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}
ATTENTION = {"contraindicated", "major", "moderate"}


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Medicine:
    """One line in the user's list, already normalised to ingredients."""

    id: str
    label: str
    ingredients: tuple[str, ...]  # RxCUIs


@dataclass(frozen=True)
class PatientContext:
    age_group: str | None = None  # child | adult | older
    pregnant: bool = False
    renal: bool = False
    hepatic: bool = False

    def active(self) -> set[str]:
        out = {c for c, on in (("pregnancy", self.pregnant), ("renal", self.renal),
                               ("hepatic", self.hepatic)) if on}  # fmt: skip
        if self.age_group == "child":
            out.add("paediatric")
        elif self.age_group == "older":
            out.add("geriatric")
        return out


# ---------------------------------------------------------------- knowledge snapshot


@dataclass(frozen=True)
class DatasetMeta:
    code: str
    name: str
    version: str | None
    licence: str


@dataclass(frozen=True)
class InteractionFact:
    a: str
    b: str
    severity: str
    provenance: str  # structured | label_text
    dataset: str
    source_ref: str
    source_url: str | None
    evidence_text: str | None = None


@dataclass(frozen=True)
class ClassTag:
    source: str  # EPC | ATC | LABEL_FLAG | MOA
    class_id: str
    name: str
    dataset: str
    review_status: str = "auto"
    evidence: str | None = None


@dataclass(frozen=True)
class ContextFact:
    rxcui: str
    context: str  # pregnancy | renal | hepatic | paediatric | geriatric
    kind: str  # contraindication | check_label
    text: str
    dataset: str
    source_ref: str


@dataclass(frozen=True)
class LabelText:
    """drug_interactions section of the representative single-ingredient label."""

    rxcui: str
    set_id: str
    title: str | None
    drug_interactions: str


@dataclass
class KnowledgeSnapshot:
    names: dict[str, str]
    interactions: list[InteractionFact] = field(default_factory=list)
    classes: dict[str, list[ClassTag]] = field(default_factory=dict)
    context: list[ContextFact] = field(default_factory=list)
    labels: dict[str, LabelText] = field(default_factory=dict)
    datasets: dict[str, DatasetMeta] = field(default_factory=dict)
    synonyms: dict[str, list[str]] = field(default_factory=dict)  # rxcui -> other names


# ---------------------------------------------------------------- outputs


@dataclass(frozen=True)
class Evidence:
    dataset: str
    dataset_name: str
    dataset_version: str | None
    record_id: str
    url: str | None = None
    quote: str | None = None


@dataclass(frozen=True)
class Finding:
    id: str
    type: str  # interaction | duplicate_ingredient | duplicate_class | cumulative | context
    severity: str
    medicines: tuple[str, ...]  # Medicine ids involved
    drug_labels: tuple[str, ...]  # what the user typed/picked
    ingredients: tuple[str, ...]  # ingredient names involved
    ingredient_ids: tuple[str, ...]  # their RxCUIs, same order
    title: str
    simple: str
    professional: str
    consider: str
    evidence: tuple[Evidence, ...]
    provenance: str  # structured | label_text | rule
    confidence: str  # high | medium | low
    rule_id: str | None = None
    related: tuple[str, ...] = ()  # notes from rules that also apply (merged to avoid repeats)
    related_rules: tuple[str, ...] = ()  # rule ids of those merged notes


@dataclass(frozen=True)
class CheckNote:
    """A 'check the label' note for the patient context: quoted text, not a ranked warning."""

    context: str
    medicine: str
    ingredient: str
    text: str
    evidence: Evidence


@dataclass(frozen=True)
class CheckResult:
    findings: tuple[Finding, ...]
    notes: tuple[CheckNote, ...]
    checked_pairs: int
    no_known_issue_pairs: tuple[tuple[str, str], ...]  # medicine label pairs with nothing found
    counts: dict[str, int]

    @property
    def attention_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ATTENTION)
