"""scope products by shop and remap product references

Revision ID: 20260217_0006
Revises: 20260217_0005
Create Date: 2026-02-17 13:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0006"
down_revision: Union[str, Sequence[str], None] = "20260217_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("products", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_products_shop_id"), "products", ["shop_id"], unique=False)

    op.execute("DROP INDEX IF EXISTS ix_products_sku")

    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE product_shop_pairs (
                old_product_id INTEGER NOT NULL,
                shop_id INTEGER NOT NULL,
                PRIMARY KEY (old_product_id, shop_id)
            ) ON COMMIT DROP
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO product_shop_pairs (old_product_id, shop_id)
            SELECT DISTINCT s.product_id, s.shop_id FROM stocks s
            UNION
            SELECT DISTINCT s.product_id, s.shop_id FROM sales s
            UNION
            SELECT DISTINCT t.product_id, t.from_shop_id FROM stock_transfers t
            UNION
            SELECT DISTINCT t.product_id, t.to_shop_id FROM stock_transfers t
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE product_shop_map (
                old_product_id INTEGER NOT NULL,
                shop_id INTEGER NOT NULL,
                new_product_id INTEGER NOT NULL,
                PRIMARY KEY (old_product_id, shop_id)
            ) ON COMMIT DROP
            """
        )
    )

    rows = conn.execute(
        sa.text(
            """
            SELECT p.id, p.sku, p.name, p.description, p.is_active, p.created_at, ps.shop_id
            FROM product_shop_pairs ps
            JOIN products p ON p.id = ps.old_product_id
            ORDER BY p.id, ps.shop_id
            """
        )
    ).fetchall()

    for row in rows:
        inserted = conn.execute(
            sa.text(
                """
                INSERT INTO products (sku, name, description, is_active, created_at, shop_id)
                VALUES (:sku, :name, :description, :is_active, :created_at, :shop_id)
                RETURNING id
                """
            ),
            {
                "sku": row[1],
                "name": row[2],
                "description": row[3],
                "is_active": row[4],
                "created_at": row[5],
                "shop_id": row[6],
            },
        ).scalar_one()

        conn.execute(
            sa.text(
                """
                INSERT INTO product_shop_map (old_product_id, shop_id, new_product_id)
                VALUES (:old_product_id, :shop_id, :new_product_id)
                """
            ),
            {
                "old_product_id": row[0],
                "shop_id": row[6],
                "new_product_id": inserted,
            },
        )

    conn.execute(
        sa.text(
            """
            UPDATE stocks s
            SET product_id = m.new_product_id
            FROM product_shop_map m
            WHERE s.product_id = m.old_product_id
              AND s.shop_id = m.shop_id
            """
        )
    )

    conn.execute(
        sa.text(
            """
            UPDATE sales s
            SET product_id = m.new_product_id
            FROM product_shop_map m
            WHERE s.product_id = m.old_product_id
              AND s.shop_id = m.shop_id
            """
        )
    )

    conn.execute(
        sa.text(
            """
            UPDATE stock_transfers t
            SET product_id = m.new_product_id
            FROM product_shop_map m
            WHERE t.product_id = m.old_product_id
              AND t.from_shop_id = m.shop_id
            """
        )
    )

    conn.execute(sa.text("DELETE FROM products WHERE shop_id IS NULL"))

    unresolved = conn.execute(sa.text("SELECT COUNT(*) FROM products WHERE shop_id IS NULL")).scalar_one()
    if unresolved:
        raise RuntimeError(f"Unable to resolve shop mapping for {unresolved} product(s)")

    op.alter_column("products", "shop_id", nullable=False)
    op.create_foreign_key(
        "fk_products_shop_id_shops",
        "products",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_products_shop_sku", "products", ["shop_id", "sku"])
    op.create_index(op.f("ix_products_sku"), "products", ["sku"], unique=False)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for 20260217_0006")