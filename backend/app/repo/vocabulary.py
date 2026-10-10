"""Build the in-memory normalisation Vocabulary from the database (once per process)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalise import Entry, Vocabulary
from app.models import (
    BrandIngredient,
    Dataset,
    DrugName,
    IndiaBrandIngredient,
    Ingredient,
    ProductIngredient,
)


def load_vocabulary(session: Session) -> Vocabulary:
    names = dict(session.execute(select(Ingredient.rxcui, Ingredient.name)).tuples().all())
    by_brand = _group(session.execute(select(BrandIngredient.brand_rxcui,
                                             BrandIngredient.ingredient_rxcui)))  # fmt: skip
    by_product = _group(session.execute(select(ProductIngredient.product_rxcui,
                                               ProductIngredient.ingredient_rxcui)))  # fmt: skip
    by_india = _group(session.execute(select(IndiaBrandIngredient.india_brand_id,
                                             IndiaBrandIngredient.ingredient_rxcui)))  # fmt: skip
    datasets = dict(session.execute(select(Dataset.id, Dataset.code)).tuples().all())

    entries: list[Entry] = []
    rows = session.execute(
        select(
            DrugName.text,
            DrugName.text_norm,
            DrugName.kind,
            DrugName.ingredient_rxcui,
            DrugName.brand_rxcui,
            DrugName.product_rxcui,
            DrugName.india_brand_id,
            DrugName.dataset_id,
        )
    )
    for text, text_norm, kind, ing, brand, product, india, ds in rows:
        if india is not None:
            ingredients, ref = by_india.get(str(india), ()), f"india_brand:{india}"
        elif brand is not None:
            ingredients, ref = by_brand.get(brand, ()), f"brand:{brand}"
        elif product is not None:
            ingredients, ref = by_product.get(product, ()), f"product:{product}"
        elif ing is not None:
            ingredients, ref = (ing,), f"ingredient:{ing}"
        else:
            continue
        entries.append(
            Entry(text, text_norm, kind, tuple(sorted(ingredients)), ref, datasets.get(ds, "?"))
        )
    # Every ingredient must be findable by its own name. drug_name only holds RxNorm's own
    # name list, so ingredients gap-filled from RxNav (domperidone, nimesulide, aceclofenac…)
    # would otherwise be reachable only through brands or synonyms.
    have = {(e.text_norm, e.ingredients) for e in entries if e.kind == "ingredient"}
    for rxcui, name, name_norm, ds in session.execute(
        select(Ingredient.rxcui, Ingredient.name, Ingredient.name_norm, Ingredient.dataset_id)
    ):
        if (name_norm, (rxcui,)) not in have:
            source = datasets.get(ds, "?")
            entries.append(
                Entry(name, name_norm, "ingredient", (rxcui,), f"ingredient:{rxcui}", source)
            )
    return Vocabulary(names, entries)


def _group(rows: object) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for key, value in rows:  # type: ignore[attr-defined]
        grouped[str(key)].add(value)
    return {k: tuple(sorted(v)) for k, v in grouped.items()}
