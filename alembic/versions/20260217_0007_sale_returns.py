"""add sale returns table

Revision ID: 20260217_0007
Revises: 20260217_0006
Create Date: 2026-02-17 20:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0007"
down_revision: Union[str, Sequence[str], None] = "20260217_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sale_returns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("processed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_buying_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_selling_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("refund_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("cost_reversed", sa.Numeric(14, 2), nullable=False),
        sa.Column("profit_reversed", sa.Numeric(14, 2), nullable=False),
        sa.Column("restocked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["processed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sale_returns_id"), "sale_returns", ["id"], unique=False)
    op.create_index(op.f("ix_sale_returns_sale_id"), "sale_returns", ["sale_id"], unique=False)
    op.create_index(op.f("ix_sale_returns_shop_id"), "sale_returns", ["shop_id"], unique=False)
    op.create_index(op.f("ix_sale_returns_product_id"), "sale_returns", ["product_id"], unique=False)
    op.create_index(
        op.f("ix_sale_returns_processed_by_user_id"),
        "sale_returns",
        ["processed_by_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_sale_returns_returned_at"), "sale_returns", ["returned_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sale_returns_returned_at"), table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_processed_by_user_id"), table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_product_id"), table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_shop_id"), table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_sale_id"), table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_id"), table_name="sale_returns")
    op.drop_table("sale_returns")
