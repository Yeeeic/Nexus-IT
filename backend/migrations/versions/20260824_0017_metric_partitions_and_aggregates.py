"""Add metric_aggregates table and downsampling RLS policies.

Revision ID: 20260824_0017
Revises: 20260824_0016
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0017"
down_revision: str | None = "20260824_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "metric_aggregates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "bucket_interval_seconds",
            sa.Integer(),
            nullable=False,
            server_default="3600",
        ),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("min_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("max_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("avg_value", sa.Numeric(14, 4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "metric_name ~ '^[a-z][a-z0-9_.-]{0,99}$'",
            name="ck_metric_aggregates_metric_name",
        ),
        sa.CheckConstraint(
            "sample_count > 0",
            name="ck_metric_aggregates_sample_count",
        ),
        sa.CheckConstraint(
            "min_value <= max_value",
            name="ck_metric_aggregates_min_max",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_metric_aggregates_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_metric_aggregates_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "device_id",
            "metric_name",
            "bucket_start",
            name="pk_metric_aggregates",
        ),
    )
    op.create_index(
        "ix_metric_aggregates_lookup",
        "metric_aggregates",
        ["organization_id", "device_id", "metric_name", "bucket_start"],
    )

    op.execute(
        """
        ALTER TABLE public.metric_aggregates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.metric_aggregates FORCE ROW LEVEL SECURITY;

        CREATE POLICY metric_aggregates_tenant_select ON public.metric_aggregates
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY metric_aggregates_tenant_insert ON public.metric_aggregates
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY metric_aggregates_tenant_update ON public.metric_aggregates
            FOR UPDATE TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY metric_aggregates_tenant_delete ON public.metric_aggregates
            FOR DELETE TO nexus_app_user
            USING (organization_id = public.current_organization_id());

        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.metric_aggregates TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("metric_aggregates")
    op.execute("RESET ROLE")
