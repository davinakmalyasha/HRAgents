"""Snapshot the cost of one evaluation's usage.

Tokens alone cannot answer "what did this candidate cost"; the price that was in
force when the evaluation ran can. The column is nullable because a provider
without operator-entered prices still records tokens, and the rollup reports
the cost as unknown rather than inventing one.

Revision ID: 0043_usage_cost
Revises: 0042_interviewer_calendar
Create Date: 2026-11-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_usage_cost"
down_revision: str | None = "0042_interviewer_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage", "cost_usd")
