"""Ingestion parsing logic, tested on small synthetic inputs (no network, no database)."""

import zipfile
from pathlib import Path

import pytest

from app.core.text import norm
from app.ingest.ddinter import split_qualifier
from app.ingest.india_brands import quote_for
from app.ingest.openfda_recalls import TextMatcher, parse_date
from app.ingest.rxnorm import RxNormRelease, parse_strength


def _conso(rxcui: str, tty: str, name: str) -> str:
    # RXCUI|LAT|TS|LUI|STT|SUI|ISPREF|RXAUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|SRL|SUPPRESS|CVF
    return f"{rxcui}|ENG||||||A{rxcui}{tty}||||RXNORM|{tty}|{rxcui}|{name}||N||"


def _rel(rxcui1: str, rela: str, rxcui2: str) -> str:
    # RXCUI1|RXAUI1|STYPE1|REL|RXCUI2|RXAUI2|STYPE2|RELA|RUI|SRUI|SAB|SL|DIR|RG|SUPPRESS|CVF
    return f"{rxcui1}||CUI|RO|{rxcui2}||CUI|{rela}|||RXNORM||||N|"


@pytest.fixture
def release(tmp_path: Path) -> RxNormRelease:
    """Augmentin: BN with two INs, an SBD made of two SCDCs, plus a PIN salt."""
    conso = [
        _conso("723", "IN", "amoxicillin"),
        _conso("48203", "IN", "clavulanate"),
        _conso("151392", "BN", "Augmentin"),
        _conso("1", "SCDC", "amoxicillin 875 MG"),
        _conso("2", "SCDC", "clavulanate 125 MG"),
        _conso("10", "SCD", "amoxicillin 875 MG / clavulanate 125 MG Oral Tablet"),
        _conso("11", "SBD", "amoxicillin 875 MG / clavulanate 125 MG Oral Tablet [Augmentin]"),
        _conso("20", "PIN", "clavulanate potassium"),
    ]
    # Each row reads "RXCUI2 RELA RXCUI1" (verified on the real 2026-09 release).
    rel = [
        _rel("723", "tradename_of", "151392"),  # Augmentin tradename_of amoxicillin
        _rel("48203", "tradename_of", "151392"),
        _rel("723", "has_ingredient", "1"),  # SCDC 1 has_ingredient amoxicillin
        _rel("48203", "has_ingredient", "2"),
        _rel("1", "consists_of", "10"),  # SCD 10 consists_of SCDC 1
        _rel("2", "consists_of", "10"),
        _rel("1", "consists_of", "11"),
        _rel("2", "consists_of", "11"),
        _rel("151392", "has_ingredient", "11"),  # SBD 11 has_ingredient BN
        _rel("48203", "form_of", "20"),  # PIN 20 form_of IN clavulanate
    ]
    path = tmp_path / "rx.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("rrf/RXNCONSO.RRF", "\n".join(conso) + "\n")
        zf.writestr("rrf/RXNREL.RRF", "\n".join(rel) + "\n")
    return RxNormRelease(path)


def test_brand_maps_to_all_its_ingredients(release: RxNormRelease) -> None:
    assert set(release.pairs("tradename_of", "BN", "IN")) == {
        ("151392", "723"),
        ("151392", "48203"),
    }


def test_products_get_ingredients_with_strengths(release: RxNormRelease) -> None:
    pi = release.product_ingredients()
    assert pi["10"] == {"723": (875.0, "MG"), "48203": (125.0, "MG")}
    assert pi["11"] == pi["10"]  # branded product has the same composition


def test_branded_product_links_to_brand(release: RxNormRelease) -> None:
    assert dict(release.pairs("has_ingredient", "SBD", "BN")) == {"11": "151392"}


def test_salt_maps_to_base_ingredient(release: RxNormRelease) -> None:
    assert list(release.pairs("form_of", "PIN", "IN")) == [("20", "48203")]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("amoxicillin 500 MG", (500.0, "MG")),
        ("insulin glargine 100 UNT/ML", (100.0, "UNT/ML")),
        ("ethinyl estradiol 0.035 MG", (0.035, "MG")),
        ("no strength here", (None, None)),
    ],
)
def test_parse_strength(name: str, expected: tuple[float | None, str | None]) -> None:
    assert parse_strength(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Timolol (ophthalmic)", ("Timolol", "ophthalmic")),
        ("Insulin human (inhalation, rapid acting)", ("Insulin human", "inhalation, rapid acting")),
        ("Insulin human (zinc)", ("Insulin human", None)),
        ("Salicylic acid (sodium)", ("Salicylic acid", None)),
        ("Warfarin", ("Warfarin", None)),
    ],
)
def test_ddinter_route_qualifiers_are_excluded(name: str, expected: tuple[str, str | None]) -> None:
    assert split_qualifier(name) == expected


def test_recall_text_matcher_prefers_longest_whole_word_names() -> None:
    matcher = TextMatcher(
        {"insulin": "1", "insulin glargine": "2", "sodium": "3", "metformin": "4", "rin": "5"}
    )
    found = matcher.find("Insulin Glargine 100 units/mL; Metformin HCl 500 mg, Sodium chloride")
    assert found == {"2", "4"}  # 'sodium' is stop-listed, 'rin' too short, 'insulin' subsumed


def test_parse_date() -> None:
    assert str(parse_date("20240131")) == "2024-01-31"
    assert parse_date("") is None


def test_quote_prefers_composition_statement() -> None:
    page = (
        "Buy now Composition AMOXYCILLIN-500MG+CLAVULANIC ACID-125MG Manufacturer/Marketer "
        "GSK Consume Type Oral Expires on"
    )
    assert quote_for(page, ["amox", "clavulan"]) == (
        "Composition AMOXYCILLIN-500MG+CLAVULANIC ACID-125MG Manufacturer/Marketer GSK"
    )


def test_norm_is_shared_by_index_and_query() -> None:
    assert norm("Augmentin 625 DUO") == norm("augmentin-625  duo")
