"""Match a medicine list against recall and quality-alert records (pure, deterministic).

Tiers, so staff are not alarmed by recalls of other products:
  batch       the batch number the user entered is listed in the alert  → act now
  product     same brand / product as the user's medicine               → check the batch
  ingredient  same ingredient, different product                       → information only
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.core.engine.model import DatasetMeta, Evidence
from app.core.normalise.vocab import strength_free
from app.core.recalls.checklist import CHECKLIST, ChecklistItem
from app.core.text import norm

MIN_BATCH_LEN = 5  # shorter batch strings would match by accident inside longer lot codes
MIN_BRAND_LEN = 4
INGREDIENT_SHOWN = 3  # most recent same-ingredient records shown per medicine and region


@dataclass(frozen=True)
class RecallRecord:
    id: int
    dataset: str
    region: str  # US | IN | WHO
    source_record_id: str
    classification: str | None  # Class I/II/III | NSQ | Spurious
    reason: str | None
    firm: str | None
    status: str | None
    report_date: date | None
    product_description: str
    lot_info: str | None
    source_url: str | None
    ingredients: tuple[str, ...] = ()
    product_rxcuis: tuple[str, ...] = ()
    brands: tuple[str, ...] = ()


@dataclass(frozen=True)
class MedicineRef:
    id: str
    label: str
    ingredients: tuple[str, ...]
    brand_names: tuple[str, ...] = ()  # what the user typed / the matched brand
    product_rxcuis: tuple[str, ...] = ()
    batch: str | None = None


@dataclass(frozen=True)
class RecallFlag:
    medicine_id: str
    medicine_label: str
    match: str  # batch | product | related | ingredient
    level: str  # serious | warning | info
    region: str
    kind: str  # e.g. "Spurious (CDSCO)", "Class II recall (US FDA)"
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


@dataclass(frozen=True)
class IngredientSummary:
    medicine_id: str
    medicine_label: str
    region: str
    total: int
    recent: tuple[RecallFlag, ...]


@dataclass(frozen=True)
class RecallResult:
    flags: tuple[RecallFlag, ...]  # batch and product matches, most serious first
    ingredient_summaries: tuple[IngredientSummary, ...]
    checklist: tuple[ChecklistItem, ...]
    coverage_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def attention_count(self) -> int:
        return sum(1 for f in self.flags if f.level in ("serious", "warning"))


LEVEL_RANK = {"serious": 0, "warning": 1, "info": 2}
MATCH_RANK = {"batch": 0, "product": 1, "related": 2, "ingredient": 3}


def check_recalls(
    medicines: list[MedicineRef],
    records: list[RecallRecord],
    datasets: dict[str, DatasetMeta] | None = None,
) -> RecallResult:
    datasets = datasets or {}
    flags: list[RecallFlag] = []
    by_ingredient: dict[tuple[str, str], list[RecallFlag]] = defaultdict(list)
    for med in medicines:
        keys = brand_keys(med.brand_names)
        batch = normalise_batch(med.batch)
        for rec in records:
            shares_ingredient = bool(set(med.ingredients) & set(rec.ingredients))
            same_product = bool(set(med.product_rxcuis) & set(rec.product_rxcuis)) or any(
                _brand_relation(key, b) == "same" for key in keys for b in rec.brands
            )
            related = not same_product and any(
                _brand_relation(key, b) == "related" for key in keys for b in rec.brands
            )
            if not (shares_ingredient or same_product or related):
                continue
            if batch and _batch_listed(batch, rec.lot_info):
                flags.append(_flag(med, rec, "batch", datasets))
            elif same_product:
                flags.append(_flag(med, rec, "product", datasets))
            elif related:
                flags.append(_flag(med, rec, "related", datasets))
            else:
                by_ingredient[(med.id, rec.region)].append(_flag(med, rec, "ingredient", datasets))
    flags.sort(
        key=lambda f: (
            MATCH_RANK[f.match],
            LEVEL_RANK[f.level],
            -(f.report_date or date.min).toordinal(),
        )
    )
    summaries = []
    labels = {m.id: m.label for m in medicines}
    for (med_id, region), items in sorted(by_ingredient.items()):
        items.sort(key=lambda f: f.report_date or date.min, reverse=True)
        summaries.append(
            IngredientSummary(
                med_id, labels[med_id], region, len(items), tuple(items[:INGREDIENT_SHOWN])
            )
        )
    notes = tuple(
        f"{meta.name}: {meta.version or 'version unknown'}"
        for code, meta in sorted(datasets.items())
        if code in {r.dataset for r in records}
    )
    return RecallResult(tuple(flags), tuple(summaries), CHECKLIST, notes)


# ------------------------------------------------------------------ matching helpers


def normalise_batch(batch: str | None) -> str | None:
    if not batch:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", batch.upper())
    return cleaned if len(cleaned) >= MIN_BATCH_LEN else None


def _batch_listed(batch: str, lot_info: str | None) -> bool:
    if not lot_info:
        return False
    return batch in re.sub(r"[^A-Z0-9]", "", lot_info.upper())


def brand_keys(names: tuple[str, ...]) -> set[str]:
    keys = set()
    for name in names:
        key = strength_free(norm(name))
        if len(key) >= MIN_BRAND_LEN:
            keys.add(key)
    return keys


def _brand_relation(key: str, recall_brand: str) -> str | None:
    """'same': 'telma' vs 'Telma 40' (only strength differs).
    'related': 'telma' vs 'Telma H' (same brand family, different product).
    None: 'crocin' vs 'crocinol'.
    """
    other = strength_free(norm(recall_brand))
    if other == key:
        return "same"
    if other.startswith(key + " "):
        return "related"
    return None


# ------------------------------------------------------------------ wording


def _kind(rec: RecallRecord) -> tuple[str, str]:
    """(label, level) for the record's own seriousness."""
    cls = (rec.classification or "").strip()
    if rec.region == "IN":
        if cls == "Spurious":
            return "Spurious drug alert (CDSCO, India)", "serious"
        return "Not of Standard Quality alert (CDSCO, India)", "warning"
    level = {"Class I": "serious", "Class II": "warning", "Class III": "info"}.get(cls, "warning")
    return f"{cls or 'Recall'} (US FDA)", level


def _flag(
    med: MedicineRef, rec: RecallRecord, match: str, datasets: dict[str, DatasetMeta]
) -> RecallFlag:
    kind, level = _kind(rec)
    if match == "batch":
        level = "serious"
        title = f"{med.label}: this batch is listed in a {kind}"
        simple = (
            f"The batch number you entered appears in an official alert for "
            f"{rec.product_description}."
        )
        consider = (
            "Consider keeping this pack aside and confirming with the supplier or the drug "
            "regulator before it is dispensed. Use the checklist below to inspect the pack."
        )
    elif match == "product":
        title = f"{med.label}: same product listed in a {kind}"
        simple = (
            "An official alert lists a product with the same name. Only the batches named in "
            "the alert are affected."
        )
        consider = "Consider checking the batch number on your pack against the alert."
    elif match == "related":
        level = "warning" if level == "serious" else level
        title = f"{med.label}: a related product with a similar name is in a {kind}"
        simple = (
            f"An official alert lists {rec.product_description}, which has a similar brand name "
            "but is a different product. Counterfeiters often copy popular brand names."
        )
        consider = "Consider checking that your pack is genuine using the checklist below."
    else:
        level = "info"
        title = f"{med.label}: other products with the same ingredient were in a {kind}"
        simple = (
            "A different product containing the same medicine was listed. This is shown for "
            "information; it does not mean your product is affected."
        )
        consider = "No action is needed unless your pack matches the product and batch listed."
    meta = datasets.get(rec.dataset)
    return RecallFlag(
        medicine_id=med.id,
        medicine_label=med.label,
        match=match,
        level=level,
        region=rec.region,
        kind=kind,
        title=title,
        simple=simple,
        consider=consider,
        product_description=rec.product_description,
        reason=rec.reason,
        firm=rec.firm,
        status=rec.status,
        report_date=rec.report_date,
        lot_info=rec.lot_info,
        evidence=Evidence(
            dataset=rec.dataset,
            dataset_name=meta.name if meta else rec.dataset,
            dataset_version=meta.version if meta else None,
            record_id=rec.source_record_id,
            url=rec.source_url,
            quote=None,
        ),
    )
