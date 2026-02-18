"""stock transfers table

Revision ID: 20260216_0003
Revises: 20260216_0002
Create Date: 2026-02-16 13:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260216_0003"
down_revision: Union[str, Sequence[str], None] = "20260216_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("from_shop_id", sa.Integer(), nullable=False),
        sa.Column("to_shop_id", sa.Integer(), nullable=False),
        sa.Column("transferred_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_buying_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("transferred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["from_shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transferred_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stock_transfers_from_shop_id"), "stock_transfers", ["from_shop_id"], unique=False)
    op.create_index(op.f("ix_stock_transfers_id"), "stock_transfers", ["id"], unique=False)
    op.create_index(op.f("ix_stock_transfers_product_id"), "stock_transfers", ["product_id"], unique=False)
    op.create_index(op.f("ix_stock_transfers_to_shop_id"), "stock_transfers", ["to_shop_id"], unique=False)
    op.create_index(op.f("ix_stock_transfers_transferred_at"), "stock_transfers", ["transferred_at"], unique=False)
    op.create_index(
        op.f("ix_stock_transfers_transferred_by_user_id"),
        "stock_transfers",
        ["transferred_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_transfers_transferred_by_user_id"), table_name="stock_transfers")
    op.drop_index(op.f("ix_stock_transfers_transferred_at"), table_name="stock_transfers")
    op.drop_index(op.f("ix_stock_transfers_to_shop_id"), table_name="stock_transfers")
    op.drop_index(op.f("ix_stock_transfers_product_id"), table_name="stock_transfers")
    op.drop_index(op.f("ix_stock_transfers_id"), table_name="stock_transfers")
    op.drop_index(op.f("ix_stock_transfers_from_shop_id"), table_name="stock_transfers")
    op.drop_table("stock_transfers")
