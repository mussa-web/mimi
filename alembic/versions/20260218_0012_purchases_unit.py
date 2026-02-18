"""add purchases.unit snapshot

Revision ID: 20260218_0012
Revises: 20260218_0011
Create Date: 2026-02-18 18:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260218_0012"
down_revision: Union[str, Sequence[str], None] = "20260218_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchases",
        sa.Column("unit", sa.String(length=24), nullable=False, server_default="piece"),
    )
    op.execute(
        "UPDATE purchases p "
        "SET unit = COALESCE(pr.unit, 'piece') "
        "FROM products pr "
        "WHERE p.product_id = pr.id"
    )


def downgrade() -> None:
    op.drop_column("purchases", "unit")

