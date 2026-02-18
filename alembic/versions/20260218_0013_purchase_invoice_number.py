"""add purchase invoice number with uniqueness per shop

Revision ID: 20260218_0013
Revises: 20260218_0012
Create Date: 2026-02-18 21:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260218_0013"
down_revision: Union[str, Sequence[str], None] = "20260218_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchases", sa.Column("invoice_number", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_purchases_shop_invoice_number",
        "purchases",
        ["shop_id", "invoice_number"],
        unique=True,
        postgresql_where=sa.text("invoice_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_purchases_shop_invoice_number", table_name="purchases")
    op.drop_column("purchases", "invoice_number")

