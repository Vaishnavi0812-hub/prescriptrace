from datetime import date

import pytest

from app.core.normalise import Entry, Normaliser, Vocabulary
from app.core.text import norm
from app.ingest.cdsco import (
    _previous_month,
    _valid_numbering,
    online_record,
    online_record_id,
    parse_expiry,
    rejoin,
    split_product,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12/2027", date(2027, 12, 1)),
        ("05-2027", date(2027, 5, 1)),
        ("Jun-2026", date(2026, 6, 1)),
        ("June 2026", date(2026, 6, 1)),
        ("Dec-26", date(2026, 12, 1)),
        ("30-04-2026", date(2026, 4, 1)),
        ("08/2026 .", date(2026, 8, 1)),
        ("46327", date(2026, 11, 1)),  # Excel serial date (45658 = 2025-01-01)
        ("NO EXPIRY", None),
        ("5 Yrs from the date of Mfg", None),
    ],
)
def test_parse_expiry(raw: str, expected: date | None) -> None:
    assert parse_expiry(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Paracetamo l", "Paracetamol"),
        ("Pantoprazol e tablets IP", "Pantoprazole tablets IP"),
        ("Cetirizine Hydrochlori de", "Cetirizine Hydrochloride"),
        ("Sodium Chloride in Water", "Sodium Chloride in Water"),  # real short word kept
        ("Solution of Iron", "Solution of Iron"),
    ],
)
def test_rejoin(raw: str, expected: str) -> None:
    assert rejoin(raw) == expected


def test_numbering_allows_section_restarts_only() -> None:
    assert _valid_numbering([1, 2, 3])
    assert _valid_numbering([1, 2, 3, 1, 2])
    assert not _valid_numbering([1, 2, 4])
    assert not _valid_numbering([2, 3])
    assert not _valid_numbering([1, 1])


ING = {"17767": "amlodipine", "54552": "perindopril", "6851": "methotrexate", "25033": "cefixime"}
N = Normaliser(
    Vocabulary(
        ING, [Entry(n, norm(n), "ingredient", (rx,), f"i:{rx}", "t") for rx, n in ING.items()]
    )
)


@pytest.mark.parametrize(
    ("product", "generic", "brand"),
    [
        (
            "Methotrexate Injection IP 15 mg/ml (Folitrax-15)",
            "Methotrexate Injection IP 15 mg/ml",
            "Folitrax-15",
        ),
        (
            "AMTAS PRP (Amlodipine and Perindopril Tablets)",
            "Amlodipine and Perindopril Tablets",
            "AMTAS PRP",
        ),
        ("Zinc Sulphate Tablets IP (N/A)", "Zinc Sulphate Tablets IP", None),
        ("Telmisartan Tablets (40mg/12.5mg)", "Telmisartan Tablets", None),
        ("Cefixime Tablets IP", "Cefixime Tablets IP", None),
    ],
)
def test_split_product(product: str, generic: str, brand: str | None) -> None:
    assert split_product(product, N) == (generic, brand)


# ---------------------------------------------------------------- CDSCO online alert database

NSQ_ROW = {
    "str_product_name": "Telmisartan Tablets  I.P. 40 mg (Telma 40)",
    "str_batch_no": "18240413",
    "dt_manufacturing_date": "May-2024",
    "dt_expiry_date": "Apr-2027",
    "str_manufactured_by": "Glenmark Pharmaceuticals Ltd.",
    "str_nsq_result": "Dissolution",
    "str_reporting_source": "CDL",
    "str_reported_by_lab_or_state": "CDL, Kolkata",
    "dt_reporting_month_year": "NOV-2025",
}


def test_online_record_maps_the_database_fields() -> None:
    rec = online_record("nsq", NSQ_ROW)
    assert rec["product"] == "Telmisartan Tablets I.P. 40 mg (Telma 40)"
    assert (rec["batch"], rec["expiry"], rec["reason"]) == ("18240413", "Apr-2027", "Dissolution")
    assert rec["reported_by"] == "CDL CDL, Kolkata"
    assert parse_expiry(rec["expiry"]) == date(2027, 4, 1)


def test_online_record_drops_placeholders_and_marks_claimed_maker() -> None:
    row = {**NSQ_ROW, "str_batch_no": "Not applicable", "str_manufactured_by": "Spurious"}
    rec = online_record("nsq", row)
    assert rec["batch"] == "" and rec["manufacturer"] == ""
    spurious = online_record(
        "spurious", {**NSQ_ROW, "str_product_name": None, "product_name_from_dtl": "Telma 40"}
    )
    assert spurious["product"] == "Telma 40"
    assert spurious["manufacturer"].endswith("(as claimed on the label)")


def test_online_record_ids_are_stable_and_unique() -> None:
    rec = online_record("nsq", NSQ_ROW)
    first = online_record_id("nsq", date(2025, 11, 1), rec, {})
    assert first == online_record_id("nsq", date(2025, 11, 1), rec, {})
    seen: dict[str, int] = {}
    ids = [online_record_id("nsq", date(2025, 11, 1), rec, seen) for _ in range(2)]
    assert ids[0] != ids[1]  # the same sample listed twice still gets two records


def test_monthly_list_reports_on_the_previous_month() -> None:
    assert _previous_month(date(2025, 6, 20)) == date(2025, 5, 1)
    assert _previous_month(date(2026, 1, 15)) == date(2025, 12, 1)
