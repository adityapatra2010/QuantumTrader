"""Baseline migration.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-06 16:20:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline initial migration."""
    pass


def downgrade() -> None:
    """Baseline downgrade."""
    pass
