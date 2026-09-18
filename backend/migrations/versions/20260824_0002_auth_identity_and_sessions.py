"""Add global identities, tenant memberships, and opaque sessions.

Revision ID: 20260824_0002
Revises: 20260824_0001
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0002"
down_revision: str | None = "20260824_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "failed_login_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 255",
            name="ck_users_email_normalized",
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'",
            name="ck_users_password_argon2id",
        ),
        sa.CheckConstraint(
            "length(btrim(full_name)) BETWEEN 1 AND 150",
            name="ck_users_full_name_not_blank",
        ),
        sa.CheckConstraint(
            "failed_login_attempts BETWEEN 0 AND 5",
            name="ck_users_failed_login_attempts_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "organization_memberships",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_memberships_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memberships_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "user_id", name="pk_organization_memberships"
        ),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_user_sessions_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at",
            name="ck_user_sessions_last_seen_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_sessions_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_user_sessions_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_user_sessions_organization_id"
        ),
        sa.UniqueConstraint(
            "session_token_hash", name="uq_user_sessions_token_hash"
        ),
    )

    op.execute(
        """
        ALTER TABLE public.organization_memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.organization_memberships FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.user_sessions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.user_sessions FORCE ROW LEVEL SECURITY;

        CREATE POLICY memberships_tenant_select
            ON public.organization_memberships
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());

        CREATE POLICY sessions_tenant_access
            ON public.user_sessions
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        REVOKE ALL ON TABLE public.users FROM PUBLIC;
        REVOKE ALL ON TABLE public.organization_memberships FROM PUBLIC;
        REVOKE ALL ON TABLE public.user_sessions FROM PUBLIC;
        GRANT SELECT ON TABLE public.organization_memberships TO nexus_app_user;
        GRANT SELECT ON TABLE public.user_sessions TO nexus_app_user;
        GRANT UPDATE (expires_at, last_seen_at, is_revoked)
            ON TABLE public.user_sessions TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("user_sessions")
    op.drop_table("organization_memberships")
    op.drop_table("users")
    op.execute("RESET ROLE")
