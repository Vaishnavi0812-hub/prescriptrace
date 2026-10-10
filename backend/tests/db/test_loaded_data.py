"""Regression checks on real loaded data. Each test skips if its dataset is not loaded,
so CI (empty database) passes while a developer's full load is checked for known facts.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]


@pytest.fixture
def conn() -> Connection:
    with get_engine().connect() as connection:
        yield connection  # type: ignore[misc]


def need(conn: Connection, code: str) -> None:
    if not conn.scalar(text("SELECT count(*) FROM dataset WHERE code = :c"), {"c": code}):
        pytest.skip(f"dataset {code} not loaded")


def ingredients_of_brand(conn: Connection, brand: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT i.name FROM brand b JOIN brand_ingredient bi ON bi.brand_rxcui = b.rxcui "
            "JOIN ingredient i ON i.rxcui = bi.ingredient_rxcui WHERE b.name = :b"
        ),
        {"b": brand},
    )
    return {r[0] for r in rows}


def severity(conn: Connection, a: str, b: str, dataset: str) -> str | None:
    return conn.scalar(
        text(
            "SELECT x.severity FROM interaction x "
            "JOIN ingredient ia ON ia.rxcui = x.ingredient_a "
            "JOIN ingredient ib ON ib.rxcui = x.ingredient_b "
            "JOIN dataset d ON d.id = x.dataset_id "
            "WHERE d.code = :d AND ((ia.name = :a AND ib.name = :b) "
            "OR (ia.name = :b AND ib.name = :a))"
        ),
        {"a": a, "b": b, "d": dataset},
    )


def test_rxnorm_combination_brand(conn: Connection) -> None:
    need(conn, "rxnorm_prescribe")
    assert ingredients_of_brand(conn, "Augmentin") == {"amoxicillin", "clavulanate"}


def test_rxnorm_product_strengths(conn: Connection) -> None:
    need(conn, "rxnorm_prescribe")
    rows = conn.execute(
        text(
            "SELECT i.name, pi.strength_value::float, pi.strength_unit FROM product p "
            "JOIN product_ingredient pi ON pi.product_rxcui = p.rxcui "
            "JOIN ingredient i ON i.rxcui = pi.ingredient_rxcui "
            "WHERE p.name = 'acetaminophen 500 MG Oral Tablet'"
        )
    ).all()
    assert [tuple(r) for r in rows] == [("acetaminophen", 500.0, "MG")]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("warfarin", "ibuprofen", "major"),
        ("sertraline", "tramadol", "major"),
        ("aspirin", "ibuprofen", "major"),  # DDInter calls it "Acetylsalicylic acid"
        ("acetaminophen", "warfarin", "moderate"),
    ],
)
def test_ddinter_known_pairs(conn: Connection, a: str, b: str, expected: str) -> None:
    need(conn, "ddinter")
    assert severity(conn, a, b, "ddinter") == expected


def test_ddinter_route_specific_entries_are_not_merged(conn: Connection) -> None:
    need(conn, "ddinter")
    refs = conn.scalar(
        text("SELECT count(*) FROM interaction WHERE source_ref LIKE '%DDInter1810%'")
    )  # DDInter1810 = "Timolol (ophthalmic)"
    assert refs == 0


def test_recall_links_have_a_basis(conn: Connection) -> None:
    need(conn, "openfda_enforcement")
    bad = conn.scalar(
        text(
            "SELECT count(*) FROM recall_link "
            "WHERE ingredient_rxcui IS NULL AND product_rxcui IS NULL AND brand_text IS NULL"
        )
    )
    assert bad == 0


def test_india_brand_resolves_and_cites_source(conn: Connection) -> None:
    need(conn, "india_brands")
    row = conn.execute(
        text(
            "SELECT string_agg(i.name, ', ' ORDER BY i.name), min(b.source_url), "
            "min(b.source_quote) FROM india_brand b "
            "JOIN india_brand_ingredient bi ON bi.india_brand_id = b.id "
            "JOIN ingredient i ON i.rxcui = bi.ingredient_rxcui WHERE b.brand = 'Dolo 650'"
        )
    ).one()
    assert row[0] == "acetaminophen"
    assert row[1].startswith("https://")
    assert "PARACETAMOL" in row[2]


def test_crocin_is_not_saffron(conn: Connection) -> None:
    """RxNorm's 'crocin' is a saffron carotenoid; the India brand must win for lookups."""
    need(conn, "india_brands")
    target = conn.scalar(
        text(
            "SELECT i.name FROM drug_name n JOIN india_brand_ingredient bi "
            "ON bi.india_brand_id = n.india_brand_id JOIN ingredient i "
            "ON i.rxcui = bi.ingredient_rxcui "
            "WHERE n.kind = 'india_brand' AND n.text_norm = 'crocin'"
        )
    )
    assert target == "acetaminophen"


def test_india_brand_with_non_us_ingredient(conn: Connection) -> None:
    """Aceclofenac is not in the US Prescribable subset; it is fetched from RxNav."""
    need(conn, "india_brands")
    names = conn.scalar(
        text(
            "SELECT string_agg(i.name, ', ' ORDER BY i.name) FROM india_brand b "
            "JOIN india_brand_ingredient bi ON bi.india_brand_id = b.id "
            "JOIN ingredient i ON i.rxcui = bi.ingredient_rxcui WHERE b.brand = 'Zerodol-P'"
        )
    )
    assert names == "aceclofenac, acetaminophen"
