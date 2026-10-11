"""Shared ingestion plumbing: downloads, dataset metadata, run bookkeeping, bulk writes."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Dataset, IngestRun

log = logging.getLogger("ingest")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
USER_AGENT = "PrescripTrace-ingest/0.1 (research; decision-support tool)"


class IngestError(RuntimeError):
    """A source is missing, changed shape, or failed validation. Never silently skipped."""


@dataclass(frozen=True)
class DatasetInfo:
    code: str
    name: str
    source_url: str
    licence: str
    licence_url: str | None = None
    region: str | None = None
    limitations: str | None = None


# ---------------------------------------------------------------- downloads


def _http(url: str, method: str = "GET", headers: Mapping[str, str] | None = None) -> Any:
    req = urllib.request.Request(  # noqa: S310 - URLs are fixed https sources in code
        url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=120)  # noqa: S310


def remote_size(url: str) -> int | None:
    try:
        with _http(url, "HEAD") as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except (urllib.error.URLError, TimeoutError):
        return None


def download(url: str, dest: Path, *, attempts: int = 8, refresh: bool = False) -> Path:
    """Resumable download with exponential backoff.

    A `<file>.complete` marker is written only after a size-verified download, so later runs
    skip the network entirely for finished files (slow/flaky servers like DDInter) while
    partial files are still resumed.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    marker = dest.with_name(dest.name + ".complete")
    if marker.exists() and dest.exists() and not refresh:
        log.info("have %s (%s bytes, verified earlier)", dest.name, dest.stat().st_size)
        return dest
    marker.unlink(missing_ok=True)
    path = _download(url, dest, attempts=attempts, refresh=refresh)
    marker.write_text(f"{path.stat().st_size}\n", encoding="utf-8")
    return path


def _download(url: str, dest: Path, *, attempts: int, refresh: bool) -> Path:
    expected = remote_size(url)
    for attempt in range(attempts):
        have = dest.stat().st_size if dest.exists() else 0
        if have and not refresh and (expected is None or have == expected):
            log.info("have %s (%s bytes)", dest.name, have)
            return dest
        if expected is not None and have > expected:
            dest.unlink()
            have = 0
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with _http(url, headers=headers) as resp, dest.open("ab" if have else "wb") as out:
                if have and resp.status != 206:  # server ignored Range: restart
                    out.truncate(0)
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
            refresh = False
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            wait = min(60, 2**attempt)
            log.warning("download %s failed (%s); retry in %ss", dest.name, exc, wait)
            time.sleep(wait)
    have = dest.stat().st_size if dest.exists() else 0
    if expected is not None and have != expected:
        raise IngestError(f"Could not download {url} ({have}/{expected} bytes)")
    return dest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


API_RETRY_SECONDS = 600  # ride out connection drops of up to ~10 minutes


def cached_json(url: str, cache_key: str, *, min_interval: float = 0.06) -> Any:
    """GET a JSON API response, cached on disk so re-runs are reproducible and offline-safe.

    min_interval keeps us under NLM's published limit of 20 requests/second. Network failures
    and 5xx/429 responses are retried until API_RETRY_SECONDS have passed; other HTTP errors
    (e.g. 404: the API changed) fail immediately so they are not hidden.
    """
    path = CACHE_DIR / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + API_RETRY_SECONDS
    attempt = 0
    while True:
        try:
            time.sleep(min_interval)
            with _http(url) as resp:
                raw = resp.read()
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:  # some government APIs answer in Windows-1252
                body = raw.decode("cp1252", errors="replace")
            data = json.loads(body)
            path.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise IngestError(f"API error {exc.code} for {url} (API changed?)") from exc
            error: Exception = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            error = exc
        if time.monotonic() > deadline:
            raise IngestError(f"API unavailable for {API_RETRY_SECONDS}s: {url} ({error})")
        attempt += 1
        log.warning("GET %s failed (%s), retrying", url, error)
        time.sleep(min(30, 2**attempt))


# ---------------------------------------------------------------- bookkeeping


@dataclass
class RunStats:
    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        log.info(message)
        self.notes.append(message)


def upsert_dataset(session: Session, info: DatasetInfo, **fields: Any) -> Dataset:
    dataset = session.scalar(select(Dataset).where(Dataset.code == info.code))
    if dataset is None:
        dataset = Dataset(code=info.code)
        session.add(dataset)
    dataset.name = info.name
    dataset.source_url = info.source_url
    dataset.licence = info.licence
    dataset.licence_url = info.licence_url
    dataset.region = info.region
    dataset.limitations = info.limitations
    for key, value in fields.items():
        setattr(dataset, key, value)
    session.flush()
    return dataset


@contextmanager
def ingest_run(session: Session, dataset: Dataset) -> Iterator[RunStats]:
    """Record an ingest run. The data writes commit only if the whole run succeeds."""
    started = datetime.now(UTC)
    stats = RunStats()
    try:
        yield stats
    except Exception as exc:
        session.rollback()
        dataset_id = session.scalar(select(Dataset.id).where(Dataset.code == dataset.code))
        if dataset_id is not None:
            session.add(_run_row(dataset_id, started, "failed", stats, f"{exc!r}"))
            session.commit()
        raise
    dataset.record_count = stats.rows_out
    session.add(_run_row(dataset.id, started, "ok", stats, None))
    session.commit()
    log.info(
        "%s: in=%s out=%s rejected=%s",
        dataset.code,
        stats.rows_in,
        stats.rows_out,
        stats.rows_rejected,
    )


def _run_row(
    dataset_id: int, started: datetime, status: str, stats: RunStats, error: str | None
) -> IngestRun:
    log_text = "\n".join([*stats.notes, *([error] if error else [])])
    return IngestRun(
        dataset_id=dataset_id,
        started_at=started,
        finished_at=datetime.now(UTC),
        status=status,
        rows_in=stats.rows_in,
        rows_out=stats.rows_out,
        rows_rejected=stats.rows_rejected,
        log=log_text[:100_000],
    )


# ---------------------------------------------------------------- bulk writes


def chunks(rows: Sequence[dict[str, Any]], size: int = 5000) -> Iterator[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def replace_rows(
    session: Session, table: Table, dataset_id: int, rows: list[dict[str, Any]]
) -> int:
    """Idempotent load: delete this dataset's rows in `table`, then insert the new set."""
    session.execute(delete(table).where(table.c.dataset_id == dataset_id))
    for batch in chunks(rows):
        session.execute(insert(table), list(batch))
    return len(rows)


def upsert_rows(
    session: Session, table: Table, rows: list[dict[str, Any]], key: Sequence[str]
) -> int:
    """INSERT … ON CONFLICT (key) DO UPDATE, batched."""
    for batch in chunks(rows):
        stmt = pg_insert(table).values(list(batch))
        updates = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in key}
        session.execute(stmt.on_conflict_do_update(index_elements=list(key), set_=updates))
    return len(rows)
