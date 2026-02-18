"""inventory schema

Revision ID: 20260216_0002
Revises: 20260216_0001
Create Date: 2026-02-16 13:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260216_0002"
down_revision: Union[str, Sequence[str], None] = "20260216_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shops_code"), "shops", ["code"], unique=True)
    op.create_index(op.f("ix_shops_id"), "shops", ["id"], unique=False)
    op.create_index(op.f("ix_shops_name"), "shops", ["name"], unique=False)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_products_id"), "products", ["id"], unique=False)
    op.create_index(op.f("ix_products_name"), "products", ["name"], unique=False)
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=True)

    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("buying_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "product_id", name="uq_stocks_shop_product"),
    )
    op.create_index(op.f("ix_stocks_id"), "stocks", ["id"], unique=False)
    op.create_index(op.f("ix_stocks_product_id"), "stocks", ["product_id"], unique=False)
    op.create_index(op.f("ix_stocks_shop_id"), "stocks", ["shop_id"], unique=False)

    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sold_by_user_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_buying_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit_selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("revenue", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("profit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("sold_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sold_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sales_id"), "sales", ["id"], unique=False)
    op.create_index(op.f("ix_sales_product_id"), "sales", ["product_id"], unique=False)
    op.create_index(op.f("ix_sales_shop_id"), "sales", ["shop_id"], unique=False)
    op.create_index(op.f("ix_sales_sold_at"), "sales", ["sold_at"], unique=False)
    op.create_index(op.f("ix_sales_sold_by_user_id"), "sales", ["sold_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sales_sold_by_user_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_sold_at"), table_name="sales")
    op.drop_index(op.f("ix_sales_shop_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_product_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_id"), table_name="sales")
    op.drop_table("sales")

    op.drop_index(op.f("ix_stocks_shop_id"), table_name="stocks")
    op.drop_index(op.f("ix_stocks_product_id"), table_name="stocks")
    op.drop_index(op.f("ix_stocks_id"), table_name="stocks")
    op.drop_table("stocks")

    op.drop_index(op.f("ix_products_sku"), table_name="products")
    op.drop_index(op.f("ix_products_name"), table_name="products")
    op.drop_index(op.f("ix_products_id"), table_name="products")
    op.drop_table("products")

    op.drop_index(op.f("ix_shops_name"), table_name="shops")
    op.drop_index(op.f("ix_shops_id"), table_name="shops")
    op.drop_index(op.f("ix_shops_code"), table_name="shops")
    op.drop_table("shops")
