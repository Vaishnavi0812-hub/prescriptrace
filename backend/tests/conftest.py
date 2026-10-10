import os

# Tests must be deterministic and offline: no rate limits, no RxNav calls. Set before any
# app module reads (and caches) the settings.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("NORMALISE_EXTERNAL", "false")
os.environ.setdefault("OFFLINE_PACK_PREBUILD", "false")

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_engine


@pytest.fixture(scope="session")
def db_available() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


@pytest.fixture
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
