"""Recall and quality-alert flagging (pure; no database or web imports)."""

from app.core.recalls.checklist import CHECKLIST, ChecklistItem
from app.core.recalls.match import (
    IngredientSummary,
    MedicineRef,
    RecallFlag,
    RecallRecord,
    RecallResult,
    check_recalls,
)

__all__ = [
    "CHECKLIST",
    "ChecklistItem",
    "IngredientSummary",
    "MedicineRef",
    "RecallFlag",
    "RecallRecord",
    "RecallResult",
    "check_recalls",
]
