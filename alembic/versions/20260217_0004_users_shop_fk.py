"""users.shop_id foreign key to shops.id

Revision ID: 20260217_0004
Revises: 20260216_0003
Create Date: 2026-02-17 11:00:00
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0004"
down_revision: Union[str, Sequence[str], None] = "20260216_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("users", sa.Column("shop_id_int", sa.Integer(), nullable=True))

    missing_codes = conn.execute(
        sa.text(
            """
            SELECT DISTINCT UPPER(TRIM(u.shop_id)) AS code
            FROM users u
            LEFT JOIN shops s ON UPPER(s.code) = UPPER(TRIM(u.shop_id))
            WHERE u.shop_id IS NOT NULL
              AND TRIM(u.shop_id) <> ''
              AND s.id IS NULL
            """
        )
    ).fetchall()

    for row in missing_codes:
        code = row[0]
        if not code:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO shops (code, name, location, is_active, created_at)
                VALUES (:code, :name, :location, :is_active, :created_at)
                """
            ),
            {
                "code": code,
                "name": code,
                "location": None,
                "is_active": True,
                "created_at": datetime.utcnow(),
            },
        )

    conn.execute(
        sa.text(
            """
            UPDATE users
            SET shop_id_int = (
                SELECT s.id
                FROM shops s
                WHERE UPPER(s.code) = UPPER(TRIM(users.shop_id))
                LIMIT 1
            )
            """
        )
    )

    unresolved = conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE shop_id_int IS NULL")).scalar_one()
    if unresolved:
        raise RuntimeError(f"Unable to resolve shop mapping for {unresolved} user(s)")

    op.drop_index(op.f("ix_users_shop_id"), table_name="users")
    op.drop_column("users", "shop_id")
    op.alter_column(
        "users",
        "shop_id_int",
        new_column_name="shop_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_users_shop_id_shops",
        "users",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_users_shop_id"), "users", ["shop_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_constraint("fk_users_shop_id_shops", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_shop_id"), table_name="users")

    op.add_column("users", sa.Column("shop_id_code", sa.String(length=100), nullable=True))
    conn.execute(
        sa.text(
            """
            UPDATE users
            SET shop_id_code = (
                SELECT s.code
                FROM shops s
                WHERE s.id = users.shop_id
                LIMIT 1
            )
            """
        )
    )

    unresolved = conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE shop_id_code IS NULL")).scalar_one()
    if unresolved:
        raise RuntimeError(f"Unable to restore shop code for {unresolved} user(s)")

    op.drop_column("users", "shop_id")
    op.alter_column(
        "users",
        "shop_id_code",
        new_column_name="shop_id",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.create_index(op.f("ix_users_shop_id"), "users", ["shop_id"], unique=False)