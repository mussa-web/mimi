"""initial auth schema

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260216_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role_enum = sa.Enum(
        "SYSTEM_OWNER",
        "BUSINESS_OWNER",
        "EMPLOYEE",
        name="userrole",
    )
    approval_status_enum = sa.Enum(
        "PENDING",
        "APPROVED",
        "REJECTED",
        name="approvalstatus",
    )
    one_time_token_type_enum = sa.Enum(
        "EMAIL_VERIFICATION",
        "PASSWORD_RESET",
        name="onetimetokentype",
    )

    bind = op.get_bind()
    user_role_enum.create(bind, checkfirst=True)
    approval_status_enum.create(bind, checkfirst=True)
    one_time_token_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("shop_id", sa.String(length=100), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("approval_status", approval_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_approval_status"), "users", ["approval_status"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_index(op.f("ix_users_shop_id"), "users", ["shop_id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)

    op.create_table(
        "one_time_tokens",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_type", one_time_token_type_enum, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_one_time_tokens_expires_at"), "one_time_tokens", ["expires_at"], unique=False)
    op.create_index(op.f("ix_one_time_tokens_id"), "one_time_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_one_time_tokens_token_hash"), "one_time_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_one_time_tokens_token_type"), "one_time_tokens", ["token_type"], unique=False)
    op.create_index(op.f("ix_one_time_tokens_user_id"), "one_time_tokens", ["user_id"], unique=False)

    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by_session_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_sessions_expires_at"), "refresh_sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_refresh_sessions_id"), "refresh_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_refresh_sessions_revoked_at"), "refresh_sessions", ["revoked_at"], unique=False)
    op.create_index(op.f("ix_refresh_sessions_token_hash"), "refresh_sessions", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_sessions_user_id"), "refresh_sessions", ["user_id"], unique=False)

    op.create_table(
        "user_security_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False),
        sa.Column("mfa_secret", sa.String(length=128), nullable=True),
        sa.Column("mfa_temp_secret", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_security_profiles_id"), "user_security_profiles", ["id"], unique=False)
    op.create_index(op.f("ix_user_security_profiles_user_id"), "user_security_profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_security_profiles_user_id"), table_name="user_security_profiles")
    op.drop_index(op.f("ix_user_security_profiles_id"), table_name="user_security_profiles")
    op.drop_table("user_security_profiles")

    op.drop_index(op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_token_hash"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_revoked_at"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_expires_at"), table_name="refresh_sessions")
    op.drop_table("refresh_sessions")

    op.drop_index(op.f("ix_one_time_tokens_user_id"), table_name="one_time_tokens")
    op.drop_index(op.f("ix_one_time_tokens_token_type"), table_name="one_time_tokens")
    op.drop_index(op.f("ix_one_time_tokens_token_hash"), table_name="one_time_tokens")
    op.drop_index(op.f("ix_one_time_tokens_id"), table_name="one_time_tokens")
    op.drop_index(op.f("ix_one_time_tokens_expires_at"), table_name="one_time_tokens")
    op.drop_table("one_time_tokens")

    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_shop_id"), table_name="users")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_approval_status"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    sa.Enum(name="onetimetokentype").drop(bind, checkfirst=True)
    sa.Enum(name="approvalstatus").drop(bind, checkfirst=True)
    sa.Enum(name="userrole").drop(bind, checkfirst=True)
