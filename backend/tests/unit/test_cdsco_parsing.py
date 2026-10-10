from datetime import date

import pytest

from app.core.normalise import Entry, Normaliser, Vocabulary
from app.core.text import norm
from app.ingest.cdsco import _valid_numbering, parse_expiry, rejoin, split_product


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
N = Normaliser(Vocabulary(ING, [Entry(n, norm(n), "ingredient", (rx,), f"i:{rx}", "t")
                                for rx, n in ING.items()]))  # fmt: skip


@pytest.mark.parametrize(
    ("product", "generic", "brand"),
    [
        ("Methotrexate Injection IP 15 mg/ml (Folitrax-15)", "Methotrexate Injection IP 15 mg/ml",
         "Folitrax-15"),
        ("AMTAS PRP (Amlodipine and Perindopril Tablets)", "Amlodipine and Perindopril Tablets",
         "AMTAS PRP"),
        ("Zinc Sulphate Tablets IP (N/A)", "Zinc Sulphate Tablets IP", None),
        ("Telmisartan Tablets (40mg/12.5mg)", "Telmisartan Tablets", None),
        ("Cefixime Tablets IP", "Cefixime Tablets IP", None),
    ],
)  # fmt: skip
def test_split_product(product: str, generic: str, brand: str | None) -> None:
    assert split_product(product, N) == (generic, brand)
