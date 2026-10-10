"""Alembic autogenerate does not detect CHECK constraint changes; this test does."""

import re

import pytest
from sqlalchemy import CheckConstraint, text

from app.db import get_engine
from app.models import Base

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("require_db")]

_IN_LIST = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def _model_in_constraints() -> list[tuple[str, str, set[str]]]:
    found = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            match = _IN_LIST.search(str(constraint.sqltext))
            if match:
                values = set(re.findall(r"'([^']*)'", match.group(2)))
                found.append((table.name, str(constraint.name), values))
    return found


@pytest.mark.parametrize(("table", "name", "values"), _model_in_constraints())
def test_database_check_constraint_matches_model(table: str, name: str, values: set[str]) -> None:
    with get_engine().connect() as conn:
        definition = conn.scalar(
            text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :n"
            ),
            {"t": table, "n": name},
        )
    assert definition is not None, f"{name} missing on {table}"
    in_db = set(re.findall(r"'([^']*)'", definition))
    assert in_db == values, f"{table}.{name}: database {in_db} != model {values}"
