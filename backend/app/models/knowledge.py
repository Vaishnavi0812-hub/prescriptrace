"""Clinical knowledge: classes, interactions, patient-context notes, label excerpts."""

from datetime import date

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SEVERITIES = ("contraindicated", "major", "moderate", "minor", "unknown")
_SEVERITY_SQL = ", ".join(f"'{s}'" for s in SEVERITIES)


class DrugClass(Base):
    __tablename__ = "drug_class"
    __table_args__ = (UniqueConstraint("source", "class_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # EPC | MEDRT_MOA | ATC | LABEL_FLAG
    class_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))


class IngredientClass(Base):
    __tablename__ = "ingredient_class"

    ingredient_rxcui: Mapped[str] = mapped_column(
        ForeignKey("ingredient.rxcui", ondelete="CASCADE"), primary_key=True
    )
    drug_class_id: Mapped[int] = mapped_column(
        ForeignKey("drug_class.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    # For LABEL_FLAG: label set_id and the quoted sentence that triggered the flag.
    evidence: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(16), default="auto")


class Interaction(Base):
    """Pairwise ingredient interaction. Stored once per pair with ingredient_a < ingredient_b."""

    __tablename__ = "interaction"
    __table_args__ = (
        UniqueConstraint("ingredient_a", "ingredient_b", "dataset_id"),
        CheckConstraint("ingredient_a < ingredient_b", name="ordered_pair"),
        CheckConstraint(f"severity IN ({_SEVERITY_SQL})", name="severity_valid"),
        CheckConstraint("provenance IN ('structured', 'label_text')", name="provenance_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_a: Mapped[str] = mapped_column(ForeignKey("ingredient.rxcui"), index=True)
    ingredient_b: Mapped[str] = mapped_column(ForeignKey("ingredient.rxcui"), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    provenance: Mapped[str] = mapped_column(String(16))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    source_ref: Mapped[str] = mapped_column(String(200))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class ContextNote(Base):
    """Patient-context note. Only sourced text; never a dose adjustment we wrote ourselves."""

    __tablename__ = "context_note"
    __table_args__ = (
        CheckConstraint(
            "context IN ('pregnancy', 'renal', 'hepatic', 'paediatric', 'geriatric')",
            name="context_valid",
        ),
        CheckConstraint("kind IN ('contraindication', 'check_label')", name="kind_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_rxcui: Mapped[str] = mapped_column(ForeignKey("ingredient.rxcui"), index=True)
    context: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
    source_ref: Mapped[str] = mapped_column(String(200))


class LabelExcerpt(Base):
    """Trimmed openFDA label: only the sections the engine and UI quote."""

    __tablename__ = "label_excerpt"

    set_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ingredient_rxcuis: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    title: Mapped[str | None] = mapped_column(Text)
    effective_time: Mapped[date | None] = mapped_column(Date)
    sections: Mapped[dict[str, str]] = mapped_column(JSONB)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id"))
