"""recall match basis values

Revision ID: 7aa4151ce579
Revises: 0dedbd5809da
Create Date: 2026-10-10 02:39:58.855557
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7aa4151ce579"
down_revision: str | None = "0dedbd5809da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Autogenerate does not detect CHECK constraint changes, so this one is written by hand.
NAME = "ck_recall_link_match_basis_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "recall_link", type_="check")
    op.create_check_constraint(
        "match_basis_valid", "recall_link", "match_basis IN ('rxcui', 'ndc', 'substance', 'text')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(NAME), "recall_link", type_="check")
    op.create_check_constraint(
        "match_basis_valid", "recall_link", "match_basis IN ('rxcui', 'ndc', 'name')"
    )
