"""Add single-use password reset tokens.

Revision ID: 20260824_0011
Revises: 20260824_0010
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0011"
down_revision: str | None = "20260824_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_revoked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose = 'PASSWORD_RESET'",
            name="ck_password_reset_tokens_purpose",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_password_reset_tokens_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_password_reset_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_pending",
        "password_reset_tokens",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("used_at IS NULL AND NOT is_revoked"),
    )
    op.execute(
        """
        REVOKE ALL ON TABLE public.password_reset_tokens FROM PUBLIC;
        ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.password_reset_tokens FORCE ROW LEVEL SECURITY;
        CREATE POLICY password_reset_auth_all
            ON public.password_reset_tokens
            FOR ALL TO nexus_auth_user
            USING (true)
            WITH CHECK (true);
        GRANT SELECT, INSERT, UPDATE
            ON TABLE public.password_reset_tokens TO nexus_auth_user;
        GRANT UPDATE (password_hash, failed_login_attempts, locked_until)
            ON TABLE public.users TO nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        REVOKE UPDATE (password_hash)
            ON TABLE public.users FROM nexus_auth_user;
        """
    )
    op.drop_index(
        "ix_password_reset_tokens_user_pending",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
    op.execute("RESET ROLE")
