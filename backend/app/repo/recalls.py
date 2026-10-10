"""Load the recall/alert records relevant to a medicine list (ingredient or brand links)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.engine import DatasetMeta
from app.core.recalls import RecallRecord
from app.core.recalls.match import brand_keys
from app.models import Dataset, Recall, RecallLink


def load_recalls(
    session: Session, rxcuis: Iterable[str], brand_names: Iterable[str] = ()
) -> tuple[list[RecallRecord], dict[str, DatasetMeta]]:
    ids = sorted(set(rxcuis))
    keys = sorted(brand_keys(tuple(brand_names)))
    conditions = [RecallLink.ingredient_rxcui.in_(ids)]
    # Brand prefix match in SQL ("telma" → "Telma 40"); exact rules are re-applied in core.
    conditions += [func.lower(RecallLink.brand_text).like(f"{k}%") for k in keys]
    recall_ids = select(RecallLink.recall_id).where(or_(*conditions)).distinct()

    links: dict[int, list[RecallLink]] = defaultdict(list)
    for link in session.scalars(select(RecallLink).where(RecallLink.recall_id.in_(recall_ids))):
        links[link.recall_id].append(link)

    datasets = {d.id: d for d in session.scalars(select(Dataset))}
    records = []
    for rec in session.scalars(select(Recall).where(Recall.id.in_(recall_ids))):
        rec_links = links.get(rec.id, [])
        records.append(
            RecallRecord(
                id=rec.id,
                dataset=datasets[rec.dataset_id].code,
                region=rec.region,
                source_record_id=rec.source_record_id,
                classification=rec.classification,
                reason=rec.reason,
                firm=rec.firm,
                status=rec.status,
                report_date=rec.report_date,
                product_description=rec.product_description or "",
                lot_info=rec.lot_info,
                source_url=rec.source_url,
                ingredients=_ids(x.ingredient_rxcui for x in rec_links),
                product_rxcuis=_ids(x.product_rxcui for x in rec_links),
                brands=tuple(sorted({x.brand_text for x in rec_links if x.brand_text})),
            )
        )
    metas = {d.code: DatasetMeta(d.code, d.name, d.version, d.licence) for d in datasets.values()}
    return records, metas


def _ids(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(sorted({v for v in values if v}))
