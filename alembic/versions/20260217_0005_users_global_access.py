"""add users.is_global_access flag

Revision ID: 20260217_0005
Revises: 20260217_0004
Create Date: 2026-02-17 12:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0005"
down_revision: Union[str, Sequence[str], None] = "20260217_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_global_access", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "is_global_access", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_global_access")