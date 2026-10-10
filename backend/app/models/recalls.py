"""Regulator recall / alert records and their links to our vocabulary."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Recall(Base):
    __tablename__ = "recall"
    __table_args__ = (
        UniqueConstraint("dataset_id", "source_record_id"),
        CheckConstraint("region IN ('US', 'IN', 'WHO')", name="region_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    region: Mapped[str] = mapped_column(String(8))
    source_record_id: Mapped[str] = mapped_column(String(100))
    classification: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    firm: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str | None] = mapped_column(String(64))
    report_date: Mapped[date | None] = mapped_column(Date, index=True)
    product_description: Mapped[str | None] = mapped_column(Text)
    lot_info: Mapped[str | None] = mapped_column(Text)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    source_url: Mapped[str | None] = mapped_column(Text)


class RecallLink(Base):
    __tablename__ = "recall_link"
    __table_args__ = (
        # rxcui/ndc: product identifiers in the record · substance: structured ingredient field
        # · text: ingredient name found in the free-text product description (lowest confidence)
        CheckConstraint(
            "match_basis IN ('rxcui', 'ndc', 'substance', 'text')", name="match_basis_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recall_id: Mapped[int] = mapped_column(ForeignKey("recall.id", ondelete="CASCADE"), index=True)
    ingredient_rxcui: Mapped[str | None] = mapped_column(ForeignKey("ingredient.rxcui"), index=True)
    product_rxcui: Mapped[str | None] = mapped_column(String(16), index=True)
    brand_text: Mapped[str | None] = mapped_column(String(300))
    match_basis: Mapped[str] = mapped_column(String(12))
