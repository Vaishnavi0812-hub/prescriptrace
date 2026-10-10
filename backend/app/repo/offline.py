"""Load everything the offline pack is built from (whole tables, read once and cached)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from app.core.engine import ClassTag, DatasetMeta, InteractionFact, KnowledgeSnapshot
from app.models import (
    Dataset,
    DrugClass,
    IndiaBrandIngredient,
    Ingredient,
    IngredientClass,
    Interaction,
    ProductIngredient,
)


def load_full_snapshot(session: Session) -> KnowledgeSnapshot:
    """Names, interactions and classes for all ingredients (no labels/context: not offline)."""
    datasets = {d.id: d for d in session.scalars(select(Dataset))}
    code = {i: d.code for i, d in datasets.items()}
    names = dict(session.execute(select(Ingredient.rxcui, Ingredient.name)).tuples().all())
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
        for r in session.scalars(select(Interaction))
    ]
    classes: dict[str, list[ClassTag]] = defaultdict(list)
    rows = session.execute(
        select(IngredientClass, DrugClass).join(
            DrugClass, DrugClass.id == IngredientClass.drug_class_id
        )
    )
    for ic, dc in rows.tuples():
        classes[ic.ingredient_rxcui].append(
            ClassTag(
                dc.source, dc.class_id, dc.name, code[ic.dataset_id], ic.review_status, ic.evidence
            )
        )
    return KnowledgeSnapshot(
        names=names,
        interactions=interactions,
        classes=dict(classes),
        datasets={
            d.code: DatasetMeta(d.code, d.name, d.version, d.licence) for d in datasets.values()
        },
    )


def common_ingredients(session: Session) -> set[str]:
    """Ingredients in an RxNorm prescribable product or a curated Indian brand."""
    query = union(
        select(ProductIngredient.ingredient_rxcui),
        select(IndiaBrandIngredient.ingredient_rxcui),
    )
    return set(session.scalars(query))
