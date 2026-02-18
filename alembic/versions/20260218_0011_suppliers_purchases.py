"""add suppliers and purchases tables

Revision ID: 20260218_0011
Revises: 20260218_0010
Create Date: 2026-02-18 17:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260218_0011"
down_revision: Union[str, Sequence[str], None] = "20260218_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "name", name="uq_suppliers_shop_name"),
    )
    op.create_index(op.f("ix_suppliers_id"), "suppliers", ["id"], unique=False)
    op.create_index(op.f("ix_suppliers_shop_id"), "suppliers", ["shop_id"], unique=False)

    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("purchased_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_buying_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("purchased_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchased_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchases_id"), "purchases", ["id"], unique=False)
    op.create_index(op.f("ix_purchases_shop_id"), "purchases", ["shop_id"], unique=False)
    op.create_index(op.f("ix_purchases_product_id"), "purchases", ["product_id"], unique=False)
    op.create_index(op.f("ix_purchases_supplier_id"), "purchases", ["supplier_id"], unique=False)
    op.create_index(op.f("ix_purchases_purchased_by_user_id"), "purchases", ["purchased_by_user_id"], unique=False)
    op.create_index(op.f("ix_purchases_purchased_at"), "purchases", ["purchased_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_purchases_purchased_at"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_purchased_by_user_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_supplier_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_product_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_shop_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_id"), table_name="purchases")
    op.drop_table("purchases")

    op.drop_index(op.f("ix_suppliers_shop_id"), table_name="suppliers")
    op.drop_index(op.f("ix_suppliers_id"), table_name="suppliers")
    op.drop_table("suppliers")

