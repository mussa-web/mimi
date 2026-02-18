"""add stock adjustments table

Revision ID: 20260217_0008
Revises: 20260217_0007
Create Date: 2026-02-17 21:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0008"
down_revision: Union[str, Sequence[str], None] = "20260217_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("adjusted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("adjusted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["adjusted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stock_adjustments_id"), "stock_adjustments", ["id"], unique=False)
    op.create_index(op.f("ix_stock_adjustments_stock_id"), "stock_adjustments", ["stock_id"], unique=False)
    op.create_index(op.f("ix_stock_adjustments_shop_id"), "stock_adjustments", ["shop_id"], unique=False)
    op.create_index(op.f("ix_stock_adjustments_product_id"), "stock_adjustments", ["product_id"], unique=False)
    op.create_index(
        op.f("ix_stock_adjustments_adjusted_by_user_id"),
        "stock_adjustments",
        ["adjusted_by_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_stock_adjustments_adjusted_at"), "stock_adjustments", ["adjusted_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_adjustments_adjusted_at"), table_name="stock_adjustments")
    op.drop_index(op.f("ix_stock_adjustments_adjusted_by_user_id"), table_name="stock_adjustments")
    op.drop_index(op.f("ix_stock_adjustments_product_id"), table_name="stock_adjustments")
    op.drop_index(op.f("ix_stock_adjustments_shop_id"), table_name="stock_adjustments")
    op.drop_index(op.f("ix_stock_adjustments_stock_id"), table_name="stock_adjustments")
    op.drop_index(op.f("ix_stock_adjustments_id"), table_name="stock_adjustments")
    op.drop_table("stock_adjustments")
