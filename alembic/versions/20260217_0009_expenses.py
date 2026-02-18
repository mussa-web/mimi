"""add expenses table

Revision ID: 20260217_0009
Revises: 20260217_0008
Create Date: 2026-02-17 22:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260217_0009"
down_revision: Union[str, Sequence[str], None] = "20260217_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("incurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_expenses_id"), "expenses", ["id"], unique=False)
    op.create_index(op.f("ix_expenses_shop_id"), "expenses", ["shop_id"], unique=False)
    op.create_index(op.f("ix_expenses_created_by_user_id"), "expenses", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_expenses_incurred_at"), "expenses", ["incurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_expenses_incurred_at"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_created_by_user_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_shop_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_id"), table_name="expenses")
    op.drop_table("expenses")
