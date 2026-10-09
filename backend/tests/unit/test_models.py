"""Schema invariants that must hold without a database."""

from app.models import SEVERITIES, Base

EXPECTED_TABLES = {
    "dataset",
    "ingest_run",
    "ingredient",
    "product",
    "product_ingredient",
    "drug_name",
    "india_brand",
    "india_brand_ingredient",
    "drug_class",
    "ingredient_class",
    "interaction",
    "context_note",
    "label_excerpt",
    "recall",
    "recall_link",
}


def test_all_planned_tables_exist() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_no_table_has_patient_identifier_columns() -> None:
    forbidden = {"patient", "patient_name", "patient_id", "name_of_patient", "mrn", "phone"}
    for table in Base.metadata.tables.values():
        assert not forbidden & {c.name for c in table.columns}, table.name


def test_every_derived_table_points_to_a_dataset() -> None:
    """Traceability rule: data loaded from a source must reference its dataset row."""
    derived = EXPECTED_TABLES - {
        "dataset",
        "product_ingredient",
        "india_brand_ingredient",
        "drug_class",
        "recall_link",
    }
    for name in derived:
        table = Base.metadata.tables[name]
        assert "dataset_id" in table.columns, name


def test_severity_order_is_most_to_least_severe() -> None:
    assert SEVERITIES == ("contraindicated", "major", "moderate", "minor", "unknown")


def test_drug_name_has_trigram_index() -> None:
    indexes = {ix.name: ix for ix in Base.metadata.tables["drug_name"].indexes}
    ix = indexes["ix_drug_name_text_norm_trgm"]
    assert ix.dialect_options["postgresql"]["using"] == "gin"
