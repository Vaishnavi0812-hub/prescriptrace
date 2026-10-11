"""CDSCO (India) drug alerts: Not of Standard Quality (NSQ) and spurious drug lists.

Sources (both official CDSCO):
  * Since Aug 2025 CDSCO publishes alerts as a searchable database, embedded in
    https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/ from
    https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug. Its JSON endpoints give one record per
    sample (product, batch, dates, manufacturer, failed test, lab, reporting month). NSQ records
    go back to Jan 2019, spurious records to Jun 2025. This is the primary source.
  * Older monthly PDF lists on the same page are used only for spurious-drug lists published
    before the database's spurious coverage starts.

PDF extraction is validated per file: serial numbers must run 1..N without gaps (a restart at 1
is allowed for a new section), every record needs a product name and batch number, and data rows
must match the header's column count. A file that fails is skipped entirely and reported, never
partly loaded. Only batches that have not expired are kept.
"""

from __future__ import annotations

import base64
import csv
import hashlib
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
from app.ingest.common import (
    CACHE_DIR,
    RAW_DIR,
    DatasetInfo,
    cached_json,
    chunks,
    download,
    ingest_run,
    upsert_dataset,
)
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
    limitations="From CDSCO's public NSQ/spurious alert database (cdscoonline.gov.in; NSQ from "
    "Jan 2019, spurious from Jun 2025) plus older spurious-drug PDF lists (strictly validated; "
    "failed files skipped, see backend/data/reports/cdsco_files.csv). Only unexpired batches are "
    "kept. Products are matched by name text; State lab reports may lag.",
)
ONLINE = "https://cdscoonline.gov.in/CDSCO"
ONLINE_VIEW = f"{ONLINE}/viewPublicNSQDrug"
ONLINE_TABS = {
    "nsq": ("filteredNsqDrugTable", "NSQ"),
    "spurious": ("filteredSpuriousDrugTable", "Spurious"),
}
REFRESH_MONTHS = 3  # recent months are re-fetched on every run (late State lab submissions)

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


@dataclass(frozen=True)
class OnlineMonth:
    tab: str  # nsq | spurious
    month: date
    records: list[dict[str, Any]]


def online_months(refresh: bool) -> list[OnlineMonth]:
    """Every published month of the CDSCO alert database, cached per month on disk."""
    today = datetime.now(UTC).date().replace(day=1)
    out = []
    for tab, (endpoint, _) in ONLINE_TABS.items():
        for year in _get_json(f"{ONLINE}/reportingYears?tab={tab}", f"years-{tab}", True):
            names = _get_json(
                f"{ONLINE}/publicReportingMonths?year={year}&tab={tab}",
                f"months-{tab}-{year}",
                refresh or int(year) >= today.year - 1,
            )
            for name in names:
                month = date(int(year), MONTHS[name[:3].lower()], 1)
                recent = (today.year - month.year) * 12 + today.month - month.month < REFRESH_MONTHS
                data = _get_json(
                    f"{ONLINE}/{endpoint}?month={name}-{year}&source=All&tab={tab}",
                    f"{tab}-{year}-{month.month:02d}",
                    refresh or recent,
                )
                out.append(OnlineMonth(tab, month, list(data.get("aaData") or [])))
    return out


def _get_json(url: str, key: str, refresh: bool) -> Any:
    if refresh:
        (CACHE_DIR / "cdsco_online" / f"{key}.json").unlink(missing_ok=True)
    return cached_json(url, f"cdsco_online/{key}", min_interval=0.5)


def online_record(tab: str, row: dict[str, Any]) -> dict[str, str]:
    """Database row → the same fields the PDF parser produces."""
    product = row.get("str_product_name") or row.get("product_name_from_dtl") or ""
    reason = row.get("str_nsq_result") or row.get("str_nsq_remarks") or ""
    lab = row.get("str_reported_by_lab_or_state") or ""

    def value(text: Any) -> str:
        cleaned = " ".join(str(text or "").split())
        return "" if _PLACEHOLDER.match(cleaned) else cleaned

    maker = value(row.get("str_manufactured_by")) or value(row.get("str_manufacturer_name"))
    if tab == "spurious" and maker:
        maker += " (as claimed on the label)"
    return {
        "product": value(product),
        "batch": value(row.get("str_batch_no")),
        "manufacture_date": value(row.get("dt_manufacturing_date")),
        "expiry": value(row.get("dt_expiry_date")),
        "manufacturer": maker,
        "reason": value(reason),
        "reported_by": " ".join(f"{row.get('str_reporting_source') or ''} {lab}".split()),
    }


# Values the database uses for "no information".
_PLACEHOLDER = re.compile(
    r"(?i)^(-+|\.+|n/?a|nil|none|na|not (?:applicable|given|mentioned|available|known)|"
    r"spurious|unknown|null)$"
)


def online_record_id(tab: str, month: date, rec: dict[str, str], seen: dict[str, int]) -> str:
    """Stable id: the database exposes none for NSQ rows, so hash the identifying fields."""
    key = "|".join([tab, f"{month:%Y-%m}", rec["product"], rec["batch"], rec["reported_by"]])
    digest = hashlib.sha1(key.encode()).hexdigest()[:12]  # noqa: S324 - identifier, not security
    seen[digest] = seen.get(digest, 0) + 1
    suffix = f"-{seen[digest]}" if seen[digest] > 1 else ""
    return f"online:{tab}:{month:%Y-%m}:{digest}{suffix}"


def run(session: Session, refresh: bool = False) -> None:
    listing = RAW_DIR / "cdsco" / "nsq_listing.html"
    download(LIST_URL, listing, refresh=True)  # small; always refresh the index
    months = online_months(refresh)
    spurious_from = min((m.month for m in months if m.tab == "spurious"), default=date.max)
    # PDFs: only spurious lists for months before the database covers them (NSQ: database from
    # 2019). A monthly list is published in the following month (the May list in June), so
    # compare the month it reports on, not its publication date.
    files = [
        f
        for f in list_files(listing.read_text(encoding="utf-8", errors="ignore"))
        if f.kind == "Spurious" and _previous_month(f.released) < spurious_from
    ]
    dataset = upsert_dataset(session, INFO, downloaded_at=datetime.now(UTC))
    normaliser = Normaliser(load_vocabulary(session))
    this_month = datetime.now(UTC).date().replace(day=1)

    with ingest_run(session, dataset) as stats:
        session.execute(delete(Recall).where(Recall.dataset_id == dataset.id))
        report: list[list[Any]] = []
        recalls: list[dict[str, Any]] = []
        links: list[tuple[str, dict[str, Any]]] = []
        seen: dict[str, int] = {}
        online_kept = 0
        for m in months:
            kind = ONLINE_TABS[m.tab][1]
            for row in m.records:
                stats.rows_in += 1
                rec = online_record(m.tab, row)
                expiry = parse_expiry(rec["expiry"])
                # A missing batch (e.g. an unlabelled spurious product) still gives a
                # product-level alert; it just cannot be matched by batch number.
                if (
                    not rec["product"]
                    or (expiry is not None and expiry < this_month)
                    or re.search(r"(?i)\(vet\.?\)|veterinary", rec["product"])
                ):
                    stats.rows_rejected += 1
                    continue
                rid = online_record_id(m.tab, m.month, rec, seen)
                generic, brand = split_product(rec["product"], normaliser)
                recalls.append(_online_row(dataset.id, kind, m.month, rec, rid))
                links.extend((rid, link) for link in _links(normaliser, generic, brand))
                online_kept += 1
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
        online_rows = sum(len(m.records) for m in months)
        stats.note(
            f"online database: {len(months)} months, {online_rows} records, "
            f"{online_kept} unexpired kept; spurious PDFs for months before {spurious_from}: "
            f"{len(files)} "
            f"listed, {loaded} loaded, {len(files) - loaded} rejected; unexpired records total: "
            f"{len(recalls)}; records linked to an ingredient: {linked}; brand-only links: "
            f"{sum(1 for _, link in links if not link['ingredient_rxcui'])}"
        )
        newest = max((m.month for m in months), default=None)
        dataset.version = f"alerts to {newest:%b %Y}" if newest else None
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


def _online_row(ds: int, kind: str, month: date, rec: dict[str, str], rid: str) -> dict[str, Any]:
    parts = [f"Batch {rec['batch']}" if rec["batch"] else "Batch not stated"]
    if rec["manufacture_date"]:
        parts.append(f"Mfg {rec['manufacture_date']}")
    if rec["expiry"]:
        parts.append(f"Exp {rec['expiry']}")
    return {
        "region": "IN",
        "source_record_id": rid,
        "classification": kind,
        "reason": rec["reason"] or None,
        "firm": _fit(rec["manufacturer"], FIRM_MAX) or None,
        "status": None,
        "report_date": month,  # reporting month (the database gives month precision)
        "product_description": rec["product"],
        "lot_info": "; ".join(parts),
        "dataset_id": ds,
        "source_url": ONLINE_VIEW,
    }


def _previous_month(day: date) -> date:
    first = day.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


FIRM_MAX = 300  # column sizes (firm, brand_text); long addresses are shortened for display


def _fit(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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
    return {"ingredient_rxcui": rxcui, "product_rxcui": None,
            "brand_text": _fit(brand, FIRM_MAX), "match_basis": "text"}  # fmt: skip


def _write_report(rows: list[list[Any]]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["released", "kind", "title", "pdf_url", "status", "detail"])
        writer.writerows(rows)
