"""Migrations must match the models and enable pg_trgm."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.main import app
from app.models import Base

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]


def test_database_is_at_head_and_matches_models() -> None:
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"


def test_pg_trgm_extension_enabled() -> None:
    with get_engine().connect() as conn:
        ext = conn.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"))
    assert ext == "pg_trgm"


def test_interaction_pair_must_be_ordered() -> None:
    with get_engine().connect() as conn:
        check = conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_interaction_ordered_pair'"
            )
        )
    assert check is not None and "ingredient_a" in check


def test_health_endpoint_reports_database() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is True
    assert body["status"] == "ok"
