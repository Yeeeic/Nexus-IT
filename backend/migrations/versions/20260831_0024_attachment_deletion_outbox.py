"""Add durable outbox for idempotent attachment physical deletion.

Revision ID: 20260831_0024
Revises: 20260830_0023
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260831_0024"
down_revision: str | None = "20260830_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")

    op.create_table(
        "attachment_deletions_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["public.organizations.id"],
            name="fk_attachment_deletions_outbox_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attachment_deletions_outbox"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_attachment_deletions_outbox_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_attachment_deletions_outbox_attempts",
        ),
    )

    op.create_index(
        "ix_attachment_deletions_outbox_pending",
        "attachment_deletions_outbox",
        ["status", "attempts", "created_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"),
    )
    op.create_index(
        "ix_attachment_deletions_outbox_org",
        "attachment_deletions_outbox",
        ["organization_id", "status"],
    )

    op.execute(
        """
        ALTER TABLE public.attachment_deletions_outbox ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.attachment_deletions_outbox FORCE ROW LEVEL SECURITY;

        CREATE POLICY attachment_deletions_outbox_tenant_isolation
            ON public.attachment_deletions_outbox
            FOR ALL
            TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        REVOKE ALL ON TABLE public.attachment_deletions_outbox FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.attachment_deletions_outbox TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("attachment_deletions_outbox")
    op.execute("RESET ROLE")
