"""Build a KnowledgeSnapshot for just the ingredients being checked (a few small queries)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.engine import (
    ClassTag,
    ContextFact,
    DatasetMeta,
    InteractionFact,
    KnowledgeSnapshot,
    LabelText,
)
from app.models import (
    ContextNote,
    Dataset,
    DrugClass,
    DrugName,
    Ingredient,
    IngredientClass,
    Interaction,
    LabelExcerpt,
)


def load_snapshot(session: Session, rxcuis: Iterable[str]) -> KnowledgeSnapshot:
    ids = sorted(set(rxcuis))
    datasets = {
        d.id: d
        for d in session.scalars(select(Dataset))  # ~10 rows
    }
    code = {i: d.code for i, d in datasets.items()}
    names = dict(
        session.execute(select(Ingredient.rxcui, Ingredient.name).where(Ingredient.rxcui.in_(ids)))
        .tuples()
        .all()
    )

    interactions = [
        InteractionFact(
            r.ingredient_a,
            r.ingredient_b,
            r.severity,
            r.provenance,
            code[r.dataset_id],
            r.source_ref,
            r.source_url,
            r.evidence_text,
        )
        for r in session.scalars(
            select(Interaction).where(
                and_(Interaction.ingredient_a.in_(ids), Interaction.ingredient_b.in_(ids))
            )
        )
    ]

    classes: dict[str, list[ClassTag]] = defaultdict(list)
    rows = session.execute(
        select(IngredientClass, DrugClass)
        .join(DrugClass, DrugClass.id == IngredientClass.drug_class_id)
        .where(IngredientClass.ingredient_rxcui.in_(ids))
    )
    for ic, dc in rows.tuples():
        classes[ic.ingredient_rxcui].append(
            ClassTag(
                dc.source, dc.class_id, dc.name, code[ic.dataset_id], ic.review_status, ic.evidence
            )
        )

    context = [
        ContextFact(c.ingredient_rxcui, c.context, c.kind, c.text, code[c.dataset_id], c.source_ref)
        for c in session.scalars(select(ContextNote).where(ContextNote.ingredient_rxcui.in_(ids)))
    ]

    labels: dict[str, LabelText] = {}
    for le in session.scalars(
        select(LabelExcerpt).where(
            func.cardinality(LabelExcerpt.ingredient_rxcuis) == 1,
            LabelExcerpt.ingredient_rxcuis[1].in_(ids),
        )
    ):
        text: str = (le.sections or {}).get("drug_interactions") or ""
        if text:
            rx = le.ingredient_rxcuis[0]
            labels[rx] = LabelText(rx, le.set_id, le.title, text)

    synonyms: dict[str, list[str]] = defaultdict(list)
    for syn_rx, syn_text in session.execute(
        select(DrugName.ingredient_rxcui, DrugName.text).where(
            DrugName.ingredient_rxcui.in_(ids), DrugName.kind == "synonym"
        )
    ).tuples():
        if syn_rx is not None:
            synonyms[syn_rx].append(syn_text)

    return KnowledgeSnapshot(
        names=names,
        interactions=interactions,
        classes=dict(classes),
        context=context,
        labels=labels,
        datasets={
            d.code: DatasetMeta(d.code, d.name, d.version, d.licence) for d in datasets.values()
        },
        synonyms=dict(synonyms),
    )
