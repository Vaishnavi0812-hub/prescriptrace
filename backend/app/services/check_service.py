"""Run one safety check: resolve items → interaction engine → recall flags → headline.

Items that are not confidently resolved and have no user selection are NOT guessed: they are
returned as unresolved (with candidates) and left out of the check until the user picks one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.engine import Medicine, PatientContext, check
from app.core.engine.model import CheckResult
from app.core.normalise import NormalisedLine, Normaliser
from app.core.recalls import MedicineRef, RecallResult, check_recalls
from app.core.summary import Summary, summarise
from app.repo.knowledge import load_snapshot
from app.repo.recalls import load_recalls
from app.schemas import api

DISCLAIMER = (
    "PrescripTrace is decision support, not a diagnostic or prescribing tool. It does not detect "
    "fake medicines; it checks official alert lists. Consider confirming with the prescriber."
)
ABSENCE_NOTE = (
    '"No known issues" means nothing was found in the datasets we use. It is not proof that a '
    "combination is safe."
)


class SelectionError(ValueError):
    """The client sent an ingredient we do not know."""


@dataclass
class _Resolved:
    item: api.CheckItem
    label: str
    ingredients: tuple[str, ...]
    how: str
    confidence: float | None
    ref: str | None


@dataclass
class CheckOutcome:
    summary: Summary
    medicines: list[_Resolved]
    unresolved: list[tuple[api.CheckItem, NormalisedLine]]
    result: CheckResult | None
    recalls: RecallResult | None


def run_check(session: Session, normaliser: Normaliser, req: api.CheckRequest) -> CheckOutcome:
    known = normaliser.vocab.ingredient_names
    resolved: list[_Resolved] = []
    unresolved: list[tuple[api.CheckItem, NormalisedLine]] = []
    for item in req.items:
        if item.selection is not None:
            unknown = [rx for rx in item.selection.ingredients if rx not in known]
            if unknown:
                raise SelectionError(f"unknown ingredient id(s) {unknown} in item {item.id}")
            ingredients = tuple(sorted(set(item.selection.ingredients)))
            resolved.append(
                _Resolved(
                    item, item.selection.label, ingredients, "selected", None, item.selection.ref
                )
            )
            continue
        line = normaliser.normalise(item.text)
        if line.status == "resolved" and line.best is not None:
            best = line.best
            resolved.append(
                _Resolved(item, best.label, best.ingredients, "resolved", line.confidence, best.ref)
            )
        else:
            unresolved.append((item, line))

    result: CheckResult | None = None
    recalls: RecallResult | None = None
    if resolved:
        rxcuis = {rx for r in resolved for rx in r.ingredients}
        meds = [Medicine(r.item.id, r.item.text, r.ingredients) for r in resolved]
        ctx = PatientContext(**req.context.model_dump())
        result = check(meds, load_snapshot(session, rxcuis), ctx)
        refs = [_medicine_ref(r) for r in resolved]
        records, datasets = load_recalls(session, rxcuis, [b for m in refs for b in m.brand_names])
        recalls = check_recalls(refs, records, datasets)
    summary = summarise(result, recalls, len(resolved), len(unresolved))
    return CheckOutcome(summary, resolved, unresolved, result, recalls)


BRAND_KINDS = ("brand:", "india_brand:", "product:")


def _medicine_ref(r: _Resolved) -> MedicineRef:
    products = (r.ref.split(":", 1)[1],) if r.ref and r.ref.startswith("product:") else ()
    # Brand matching only for medicines identified as a brand. A generic ("Warfarin 5mg") would
    # otherwise "match" US recall records whose brand field holds the generic name.
    is_brand = bool(r.ref and r.ref.startswith(BRAND_KINDS))
    return MedicineRef(
        id=r.item.id,
        label=r.item.text,
        ingredients=r.ingredients,
        brand_names=(r.item.text, r.label) if is_brand else (),
        product_rxcuis=products,
        batch=r.item.batch,
    )
