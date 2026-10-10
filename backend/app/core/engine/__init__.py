"""Deterministic interaction engine (pure; no database or web imports)."""

from app.core.engine.engine import check
from app.core.engine.model import (
    CheckNote,
    CheckResult,
    ClassTag,
    ContextFact,
    DatasetMeta,
    Evidence,
    Finding,
    InteractionFact,
    KnowledgeSnapshot,
    LabelText,
    Medicine,
    PatientContext,
)
from app.core.engine.rules import RuleSet, load_rules

__all__ = [
    "CheckNote",
    "CheckResult",
    "ClassTag",
    "ContextFact",
    "DatasetMeta",
    "Evidence",
    "Finding",
    "InteractionFact",
    "KnowledgeSnapshot",
    "LabelText",
    "Medicine",
    "PatientContext",
    "RuleSet",
    "check",
    "load_rules",
]
