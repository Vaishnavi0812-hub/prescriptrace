"""Process-wide state: the normalisation vocabulary, loaded once at startup."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.core.normalise import Normaliser, Vocabulary
from app.db import _session_factory
from app.repo.vocabulary import load_vocabulary
from app.services.rxnav_external import RxNavSuggestions

log = logging.getLogger(__name__)
MIN_ENTRIES = 1000  # fewer means the datasets have not been loaded


@dataclass
class AppState:
    vocabulary: Vocabulary | None = None
    normaliser: Normaliser | None = None

    @property
    def ready(self) -> bool:
        return self.normaliser is not None


_state = AppState()
_lock = threading.Lock()


def load_state() -> AppState:
    """(Re)build the vocabulary from the database. Safe to call again after ingestion."""
    settings = get_settings()
    session = _session_factory()()
    try:
        vocab = load_vocabulary(session)
    except SQLAlchemyError as exc:
        log.warning("vocabulary not loaded: %s", exc)
        return _state
    finally:
        session.close()
    if len(vocab.entries) < MIN_ENTRIES:
        log.warning("vocabulary has %s entries; run the ingestion first", len(vocab.entries))
        return _state
    external = RxNavSuggestions(vocab) if settings.normalise_external else None
    normaliser = Normaliser(
        vocab,
        auto_accept=settings.normalise_auto_accept,
        confirm_min=settings.normalise_confirm_min,
        external=external,
    )
    with _lock:
        _state.vocabulary, _state.normaliser = vocab, normaliser
    log.info("vocabulary loaded: %s names", len(vocab.entries))
    return _state


def get_state() -> AppState:
    return _state
