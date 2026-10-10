"""Build the offline pack once per process (about 10 s) and keep it gzipped in memory."""

from __future__ import annotations

import gzip
import json
import threading
from dataclasses import asdict, dataclass

from app.core.engine.rules import load_rules
from app.core.normalise import Vocabulary
from app.core.offline_pack import build_pack
from app.core.recalls.checklist import CHECKLIST
from app.db import _session_factory
from app.repo.offline import common_ingredients, load_full_snapshot
from app.services.check_service import ABSENCE_NOTE, DISCLAIMER

LICENCE_NOTICE = (
    "Contains interaction data from DDInter 2.0 (CC BY-NC-SA 4.0: non-commercial use only; "
    "share derived data under the same licence) and MED-RT via RxClass."
)


@dataclass(frozen=True)
class BuiltPack:
    version: str
    generated_at: str
    gzipped: bytes
    raw_size: int


_cache: dict[int, BuiltPack] = {}  # keyed by id(vocabulary): rebuilt after a data reload
_lock = threading.Lock()


def get_pack(vocab: Vocabulary) -> BuiltPack:
    key = id(vocab)
    with _lock:
        if key not in _cache:
            _cache.clear()
            _cache[key] = _build(vocab)
        return _cache[key]


def _build(vocab: Vocabulary) -> BuiltPack:
    session = _session_factory()()
    try:
        pack = build_pack(
            load_full_snapshot(session),
            vocab.entries,
            load_rules(),
            common_ingredients(session),
            # Fixed wording shown with every result, so offline results say what online ones do.
            extra={
                "licence_notice": LICENCE_NOTICE,
                "disclaimer": DISCLAIMER,
                "absence_note": ABSENCE_NOTE,
                "checklist": [asdict(item) for item in CHECKLIST],
            },
        )
    finally:
        session.close()
    raw = json.dumps(pack, separators=(",", ":"), ensure_ascii=False).encode()
    return BuiltPack(pack["version"], pack["generated_at"], gzip.compress(raw, 6), len(raw))
