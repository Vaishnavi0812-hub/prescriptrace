"""Drug vocabulary: ingredients, products, searchable names, curated Indian brands."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Ingredient(Base):
    """RxNorm ingredient (IN/PIN): the unit every interaction and class joins on."""

    __tablename__ = "ingredient"

    rxcui: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    name_norm: Mapped[str] = mapped_column(String(300), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))


class Product(Base):
    """RxNorm clinical/branded drug or pack (SCD, SBD, GPCK, BPCK)."""

    __tablename__ = "product"

    rxcui: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    tty: Mapped[str] = mapped_column(String(8))
    dose_form: Mapped[str | None] = mapped_column(String(200))
    brand_name: Mapped[str | None] = mapped_column(String(300), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))


class ProductIngredient(Base):
    __tablename__ = "product_ingredient"

    product_rxcui: Mapped[str] = mapped_column(
        ForeignKey("product.rxcui", ondelete="CASCADE"), primary_key=True
    )
    ingredient_rxcui: Mapped[str] = mapped_column(ForeignKey("ingredient.rxcui"), primary_key=True)
    strength_value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    strength_unit: Mapped[str | None] = mapped_column(String(32))


class DrugName(Base):
    """Every searchable string (generic, brand, synonym, INN, Indian brand) for autocomplete."""

    __tablename__ = "drug_name"
    __table_args__ = (
        Index(
            "ix_drug_name_text_norm_trgm",
            "text_norm",
            postgresql_using="gin",
            postgresql_ops={"text_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(300))
    text_norm: Mapped[str] = mapped_column(String(300))
    # ingredient | brand | synonym | ddinter | india_brand
    kind: Mapped[str] = mapped_column(String(16), index=True)
    ingredient_rxcui: Mapped[str | None] = mapped_column(ForeignKey("ingredient.rxcui"))
    product_rxcui: Mapped[str | None] = mapped_column(ForeignKey("product.rxcui"))
    india_brand_id: Mapped[int | None] = mapped_column(ForeignKey("india_brand.id"))
    country: Mapped[str | None] = mapped_column(String(2))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    source_ref: Mapped[str | None] = mapped_column(String(200))


class IndiaBrand(CreatedAtMixin, Base):
    """Hand-curated Indian brand. Every row must cite where it was verified."""

    __tablename__ = "india_brand"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(200), index=True)
    strength_text: Mapped[str | None] = mapped_column(String(100))
    dose_form: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(32))  # cdsco_list | manufacturer_page | ...
    source_url: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[str] = mapped_column(String(100))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))


class IndiaBrandIngredient(Base):
    __tablename__ = "india_brand_ingredient"

    india_brand_id: Mapped[int] = mapped_column(
        ForeignKey("india_brand.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_rxcui: Mapped[str] = mapped_column(ForeignKey("ingredient.rxcui"), primary_key=True)
    strength_value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    strength_unit: Mapped[str | None] = mapped_column(String(32))
