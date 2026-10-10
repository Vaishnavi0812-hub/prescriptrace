"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.base import Base
from app.models.knowledge import (
    SEVERITIES,
    ContextNote,
    DrugClass,
    IngredientClass,
    Interaction,
    LabelExcerpt,
)
from app.models.provenance import Dataset, IngestRun
from app.models.recalls import Recall, RecallLink
from app.models.vocab import (
    Brand,
    BrandIngredient,
    DrugName,
    IndiaBrand,
    IndiaBrandIngredient,
    Ingredient,
    Product,
    ProductIngredient,
)

__all__ = [
    "SEVERITIES",
    "Base",
    "Brand",
    "BrandIngredient",
    "ContextNote",
    "Dataset",
    "DrugClass",
    "DrugName",
    "IndiaBrand",
    "IndiaBrandIngredient",
    "IngestRun",
    "Ingredient",
    "IngredientClass",
    "Interaction",
    "LabelExcerpt",
    "Product",
    "ProductIngredient",
    "Recall",
    "RecallLink",
]
