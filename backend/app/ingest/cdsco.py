"""CDSCO (India) drug alerts: Not of Standard Quality (NSQ) and spurious drug lists.

Source: monthly PDF tables listed at https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/.
As of 2026-10 that page lists alerts only up to mid-2025; CDSCO announced (Aug 2025, scanned
notice, OCR'd) a "new searchable link" that could not be found in machine-readable form. Newer
alerts are therefore MISSING, and the dataset's limitations say so.

Extraction is validated per file: serial numbers must run 1..N without gaps (a restart at 1 is
allowed for a new section), every record needs a product name and batch number, and data rows
must match the header's column count. A file that fails is skipped entirely and reported, never
partly loaded. Only batches that have not expired are kept.
"""

from __future__ import annotations

import base64
import csv
import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pdfplumber
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.normalise import Normaliser, parse
from app.ingest.common import RAW_DIR, DatasetInfo, chunks, download, ingest_run, upsert_dataset
from app.models import Recall, RecallLink
from app.repo.vocabulary import load_vocabulary

log = logging.getLogger("ingest.cdsco")

BASE = "https://cdsco.gov.in"
LIST_URL = f"{BASE}/opencms/opencms/en/Notifications/nsq-drugs/"
FILE_URL = (
    f"{BASE}/opencms/opencms/system/modules/CDSCO.WEB/elements/"
    "download_file_division.jsp?num_id={}"
)
SINCE = date(2023, 7, 1)
REPORT = Path(__file__).resolve().parents[2] / "data" / "reports" / "cdsco_files.csv"
INFO = DatasetInfo(
    code="cdsco_alerts",
    name="CDSCO NSQ and spurious drug alerts (India)",
    source_url=LIST_URL,
    licence="Government of India public notices (CDSCO); no explicit licence stated",
    region="IN",
    limitations="Covers alerts published up to mid-2025 only: CDSCO's newer alert portal could "
    "not be accessed. Parsed from PDF tables with strict validation; files that failed are "
    "skipped (see backend/data/reports/cdsco_files.csv). Only unexpired batches are kept.",
)

_ITEM = re.compile(
    r'(?is)num_id=([A-Za-z0-9=]+)[^>]*>\s*<span class="font_black">(.*?)</span>.*?'
    r"(\d{4}-[A-Za-z]{3}-\d{2})"
)
_IFRAME = re.compile(r"""(?i)<iframe[^>]+src=['"]([^'"]+)['"]""")
_SNO = re.compile(r"^\s*(\d{1,4})\s*\.?\s*$")
_PAREN = re.compile(r"\(([^()]{2,60})\)")
# Parenthesised text that is not a brand: "(Vet.)", "(N/A)", "(40mg/12.5mg)", "(D5)".
_NOT_BRAND = re.compile(
    r"(?i)^(vet\.?|n/?a|nil|none|-+|d\d+|[\d.,\s/%+]*(?:(?:mg|mcg|ml|gm?|iu|w/v)[\d.,\s/%+]*)*)$"
)
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
EXCEL_EPOCH = date(1899, 12, 30)

# Header keywords → field (first match wins for each column).
FIELDS = [
    ("product", ("product", "name of drug", "drug name", "name of the drug", "name of drugs")),
    ("batch", ("batch",)),
    ("expiry", ("expiry", "exp.", "date of exp")),
    ("manufacture_date", ("manufactur", "mfg", "date of manufacture")),
    ("manufacturer", ("manufactured by", "name of manufacturer", "manufacturer")),
    ("reason", ("nsq result", "reason", "result", "test")),
    ("reported_by", ("reported", "drawn by", "laboratory")),
]


@dataclass(frozen=True)
class AlertFile:
    num_id: str
    title: str
    released: date
    kind: str  # NSQ | Spurious

    @property
    def doc_id(self) -> int:
        return int(base64.b64decode(self.num_id).decode())


def list_files(html: str) -> list[AlertFile]:
    out = {}
    for num_id, title, released in _ITEM.findall(html):
        title = " ".join(re.sub(r"<[^>]+>", " ", title).split())
        lowered = title.lower()
        if "spurious" in lowered and "not of standard" not in lowered and "nsq" not in lowered:
            kind = "Spurious"
        elif "nsq" in lowered or "not of standard" in lowered or "drug alert" in lowered:
            kind = "NSQ"
        else:
            continue
        day = datetime.strptime(released, "%Y-%b-%d").replace(tzinfo=UTC).date()
        if day >= SINCE:
            out[num_id] = AlertFile(num_id, title, day, kind)
    return sorted(out.values(), key=lambda f: (f.released, f.doc_id))


SHORT_WORDS = {"of", "in", "as", "or", "to", "on", "an", "at", "by", "is", "it", "be", "no",
               "do", "so", "up", "if", "a", "i"}  # fmt: skip


def rejoin(text: str) -> str:
    """Undo PDF line wraps inside words: 'Paracetamo l' → 'Paracetamol', 'Hydrochlori de'.

    Only a 1-2 letter lowercase fragment after a 4+ letter word is glued back, and never a real
    short word ('Sodium Chloride in Water' stays as it is).
    """

    def glue(match: re.Match[str]) -> str:
        fragment = match.group(2)
        return match.group(0) if fragment in SHORT_WORDS else match.group(1) + fragment

    return re.sub(r"([A-Za-z]{4,}) ([a-z]{1,2})\b", glue, text)


def parse_expiry(text: str) -> date | None:
    """Month precision. Handles 12/2027, 12-27, Jun-2026, June 2026, 30-04-2026, Excel serials."""
    t = re.sub(r"\s+", "", text.lower()).strip(".,;:")
    if re.fullmatch(r"\d{5}", t) and 40000 <= int(t) <= 60000:  # Excel serial date
        day = EXCEL_EPOCH + timedelta(days=int(t))
        return date(day.year, day.month, 1)
    numeric = re.fullmatch(r"\d{1,2}[/.-](\d{1,2})[/.-](\d{2,4})", t) or re.fullmatch(
        r"(\d{1,2})[/.-](\d{2,4})", t
    )  # dd-mm-yyyy, or mm-yyyy
    if numeric:
        month, year = int(numeric.group(1)), int(numeric.group(2))
    elif m := re.fullmatch(r"([a-z]{3})[a-z]*[-/,.]?(\d{2,4})", t):
        if m.group(1) not in MONTHS:
            return None
        month, year = MONTHS[m.group(1)], int(m.group(2))
    else:
        return None
    if year < 100:
        year += 2000
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return None
    return date(year, month, 1)


def split_product(product: str, normaliser: Normaliser) -> tuple[str, str | None]:
    """(generic text, brand or None). Handles both 'Generic (BRAND)' and 'BRAND (Generic)'."""
    match = _PAREN.search(product)
    if not match:
        return product, None
    inside = match.group(1).strip()
    outside = " ".join(_PAREN.sub(" ", product).split())
    if _NOT_BRAND.match(inside) or not parse(inside).core:
        return outside, None  # "(Vet.)", "(40mg/12.5mg)", "(EC)", "(Lyophilized)"
    if normaliser.normalise(inside).status == "resolved" and (
        normaliser.normalise(outside).status != "resolved"
    ):
        return inside, outside or None  # "AMTAS PRP (Amlodipine and Perindopril Tablets)"
    return outside, inside


def _clean(cell: str | None) -> str:
    return rejoin(" ".join((cell or "").split()))


def _header_map(header: list[str | None]) -> dict[str, int] | None:
    columns: dict[str, int] = {}
    for idx, cell in enumerate(header):
        low = _clean(cell).lower().replace("manufact uring", "manufacturing")
        for field, keys in FIELDS:
            if field not in columns and any(k in low for k in keys):
                if field == "manufacture_date" and "by" in low:
                    continue  # "Manufactured By" is the manufacturer, not a date
                columns[field] = idx
                break
    return columns if {"product", "batch"} <= columns.keys() else None


def _valid_numbering(numbers: list[int]) -> bool:
    """1..N, allowing restarts at 1 for new sections (e.g. one block per laboratory)."""
    expected = 1
    for n in numbers:
        if n == expected:
            expected += 1
        elif n == 1 and expected > 2:
            expected = 2
        else:
            return False
    return True


def parse_pdf(path: Path) -> tuple[list[dict[str, str]], str | None]:
    """Return (records, None) or ([], reason-for-rejection)."""
    with pdfplumber.open(path) as pdf:
        rows = [r for page in pdf.pages for table in page.extract_tables() for r in table]
    if not rows:
        return [], "no tables found (scanned PDF?)"
    header_idx = next((i for i, r in enumerate(rows) if _header_map(r)), None)
    if header_idx is None:
        return [], "no recognisable header"
    header = rows[header_idx]
    cols = _header_map(header)
    if cols is None:
        return [], "no recognisable header"
    records: list[dict[str, str]] = []
    for row in rows[header_idx + 1 :]:
        if sum(1 for c in row if _clean(c)) <= 1 and not _SNO.match(_clean(row[0])):
            continue  # footnote/remark row spanning the table, or empty row
        if _header_map(row):
            continue  # header repeated on a new page
        if len(row) != len(header):
            return [], f"row with {len(row)} cells, header has {len(header)}"
        cells = [_clean(c) for c in row]
        sno = _SNO.match(cells[0]) if cells[0] else None
        if sno:
            records.append({f: cells[i] for f, i in cols.items()} | {"sno": sno.group(1)})
        elif records:  # continuation line of the previous record
            for f, i in cols.items():
                if cells[i]:
                    records[-1][f] = rejoin(f"{records[-1][f]} {cells[i]}".strip())
    if not records:
        return [], "no numbered records"
    numbers = [int(r["sno"]) for r in records]
    if not _valid_numbering(numbers):
        return [], f"serial numbers not 1..N (got {numbers[:5]}…{numbers[-3:]})"
    if any(not r.get("product") or not r.get("batch") for r in records):
        return [], "record without product or batch"
    return records, None


def run(session: Session, refresh: bool = False) -> None:
    listing = RAW_DIR / "cdsco" / "nsq_listing.html"
    download(LIST_URL, listing, refresh=True)  # small; always refresh the index
    files = list_files(listing.read_text(encoding="utf-8", errors="ignore"))
    dataset = upsert_dataset(session, INFO, downloaded_at=datetime.now(UTC))
    normaliser = Normaliser(load_vocabulary(session))
    this_month = datetime.now(UTC).date().replace(day=1)

    with ingest_run(session, dataset) as stats:
        session.execute(delete(Recall).where(Recall.dataset_id == dataset.id))
        report: list[list[Any]] = []
        recalls: list[dict[str, Any]] = []
        links: list[tuple[str, dict[str, Any]]] = []
        for f in files:
            pdf_url = _pdf_url(f, refresh)
            if pdf_url is None:
                report.append([f.released, f.kind, f.title, "", "rejected", "no PDF link"])
                continue
            path = download(pdf_url, RAW_DIR / "cdsco" / f"{f.doc_id}.pdf", refresh=refresh)
            records, problem = parse_pdf(path)
            kept = 0
            for rec in records:
                stats.rows_in += 1
                expiry = parse_expiry(rec.get("expiry", ""))
                if expiry is not None and expiry < this_month:
                    stats.rows_rejected += 1
                    continue
                if re.search(r"(?i)\(vet\.?\)|veterinary", rec["product"]):
                    stats.rows_rejected += 1
                    continue
                rid = f"{f.doc_id}:{rec['sno']}"
                generic, brand = split_product(rec["product"], normaliser)
                recalls.append(_recall_row(dataset.id, f, rec, rid, pdf_url))
                links.extend((rid, link) for link in _links(normaliser, generic, brand))
                kept += 1
            status = "rejected" if problem else "loaded"
            detail = problem or f"{len(records)} records, {kept} unexpired"
            report.append([f.released, f.kind, f.title, pdf_url, status, detail])
        id_by_rid: dict[str, int] = {}
        for batch in chunks(recalls):
            new_ids = session.scalars(insert(Recall).returning(Recall.id), list(batch)).all()
            id_by_rid.update(zip((r["source_record_id"] for r in batch), new_ids, strict=True))
        link_rows = [{**link, "recall_id": id_by_rid[rid]} for rid, link in links]
        for batch in chunks(link_rows):
            session.execute(insert(RecallLink), list(batch))
        stats.rows_out = len(recalls)
        loaded = sum(1 for r in report if r[4] == "loaded")
        linked = len({rid for rid, link in links if link["ingredient_rxcui"]})
        stats.note(
            f"files: {len(files)} listed since {SINCE}, {loaded} loaded, "
            f"{len(files) - loaded} rejected; unexpired records: {len(recalls)}; "
            f"records linked to an ingredient: {linked}; brand-only links: "
            f"{sum(1 for _, link in links if not link['ingredient_rxcui'])}"
        )
        newest = max((f.released for f in files), default=None)
        dataset.version = f"alerts published to {newest}" if newest else None
        _write_report(report)


def _pdf_url(f: AlertFile, refresh: bool) -> str | None:
    wrapper = RAW_DIR / "cdsco" / f"{f.doc_id}.html"
    download(FILE_URL.format(f.num_id), wrapper, refresh=refresh)
    match = _IFRAME.search(wrapper.read_text(encoding="utf-8", errors="ignore"))
    if not match:
        return None
    return BASE + urllib.parse.quote(match.group(1), safe="/:")


def _recall_row(ds: int, f: AlertFile, rec: dict[str, str], rid: str, url: str) -> dict[str, Any]:
    lot = f"Batch {rec['batch']}"
    if rec.get("manufacture_date"):
        lot += f"; Mfg {rec['manufacture_date']}"
    if rec.get("expiry"):
        lot += f"; Exp {rec['expiry']}"
    return {
        "region": "IN",
        "source_record_id": rid,
        "classification": f.kind,
        "reason": rec.get("reason") or None,
        "firm": rec.get("manufacturer") or None,
        "status": None,  # CDSCO lists carry no recall status
        "report_date": f.released,
        "product_description": rec["product"],
        "lot_info": lot,
        "dataset_id": ds,
        "source_url": url,
    }


def _links(normaliser: Normaliser, generic: str, brand: str | None) -> list[dict[str, Any]]:
    """Ingredient links (only if confidently resolved) and the brand text, if any."""
    out: list[dict[str, Any]] = []
    result = normaliser.normalise(generic)
    if result.status == "resolved" and result.best is not None:
        out = [_link(rx, brand) for rx in result.best.ingredients]
    if brand and not out:
        out = [_link(None, brand)]
    return out


def _link(rxcui: str | None, brand: str | None) -> dict[str, Any]:
    return {"ingredient_rxcui": rxcui, "product_rxcui": None, "brand_text": brand,
            "match_basis": "text"}  # fmt: skip


def _write_report(rows: list[list[Any]]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["released", "kind", "title", "pdf_url", "status", "detail"])
        writer.writerows(rows)
