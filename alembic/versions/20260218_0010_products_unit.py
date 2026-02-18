"""add products.unit of measure

Revision ID: 20260218_0010
Revises: 20260217_0009
Create Date: 2026-02-18 13:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260218_0010"
down_revision: Union[str, Sequence[str], None] = "20260217_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("unit", sa.String(length=24), nullable=False, server_default="piece"),
    )
    op.execute(
        "UPDATE products SET unit = 'piece' "
        "WHERE unit IS NULL OR unit NOT IN ('piece','kg','litre','carton')"
    )


def downgrade() -> None:
    op.drop_column("products", "unit")

