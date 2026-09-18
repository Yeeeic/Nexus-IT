"""Add durable metric ingestion, telemetry, DLQ, and alerts.

Revision ID: 20260824_0013
Revises: 20260824_0012
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0013"
down_revision: str | None = "20260824_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


batch_status_enum = postgresql.ENUM(
    "RECEIVED",
    "PROCESSING",
    "PROCESSED",
    "DLQ",
    "AWAITING_REUPLOAD",
    "DLQ_EXHAUSTED",
    name="batch_status_enum",
    create_type=False,
)
comparison_operator_enum = postgresql.ENUM(
    "GT",
    "GTE",
    "LT",
    "LTE",
    "EQ",
    name="comparison_operator_enum",
    create_type=False,
)
alert_severity_enum = postgresql.ENUM(
    "INFO",
    "WARNING",
    "CRITICAL",
    name="alert_severity_enum",
    create_type=False,
)
alert_status_enum = postgresql.ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    "SUPPRESSED",
    name="alert_status_enum",
    create_type=False,
)


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        CREATE TYPE batch_status_enum AS ENUM (
            'RECEIVED', 'PROCESSING', 'PROCESSED', 'DLQ',
            'AWAITING_REUPLOAD', 'DLQ_EXHAUSTED'
        );
        CREATE TYPE comparison_operator_enum AS ENUM ('GT', 'GTE', 'LT', 'LTE', 'EQ');
        CREATE TYPE alert_severity_enum AS ENUM ('INFO', 'WARNING', 'CRITICAL');
        CREATE TYPE alert_status_enum AS ENUM (
            'OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED'
        );
        """
    )

    op.create_table(
        "metric_batches",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            batch_status_enum,
            nullable=False,
            server_default="RECEIVED",
        ),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reprocess_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_summary", sa.String(length=255), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sample_count BETWEEN 1 AND 2000",
            name="ck_metric_batches_sample_count",
        ),
        sa.CheckConstraint(
            "retry_count BETWEEN 0 AND 3",
            name="ck_metric_batches_retry_count",
        ),
        sa.CheckConstraint(
            "reprocess_count BETWEEN 0 AND 3",
            name="ck_metric_batches_reprocess_count",
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'",
            name="ck_metric_batches_payload_digest",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,49}$'",
            name="ck_metric_batches_error_code",
        ),
        sa.CheckConstraint(
            "payload_json IS NULL OR ("
            "jsonb_typeof(payload_json) = 'array' "
            "AND pg_column_size(payload_json) <= 524288)",
            name="ck_metric_batches_payload_bounded_array",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_metric_batches_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "device_id",
            "id",
            name="pk_metric_batches",
        ),
    )
    op.create_index(
        "ix_metric_batches_worker",
        "metric_batches",
        ["organization_id", "status", "received_at"],
    )

    op.create_table(
        "metric_samples",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("metric_value", sa.Numeric(14, 4), nullable=False),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "metric_name ~ '^[a-z][a-z0-9_.-]{0,99}$'",
            name="ck_metric_samples_name",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(labels) = 'object' AND pg_column_size(labels) <= 8192",
            name="ck_metric_samples_labels_bounded_object",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_metric_samples_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "id",
            "recorded_at",
            name="pk_metric_samples",
        ),
        postgresql_partition_by="RANGE (recorded_at)",
    )
    op.execute(
        """
        CREATE TABLE public.metric_samples_default
            PARTITION OF public.metric_samples DEFAULT;
        CREATE INDEX ix_metric_samples_device_recorded_at
            ON public.metric_samples (
                organization_id, device_id, recorded_at DESC
            );
        """
    )

    op.create_table(
        "alert_rules",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("operator", comparison_operator_enum, nullable=False),
        sa.Column("threshold_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("severity", alert_severity_enum, nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 150",
            name="ck_alert_rules_name",
        ),
        sa.CheckConstraint(
            "metric_name ~ '^[a-z][a-z0-9_.-]{0,99}$'",
            name="ck_alert_rules_metric_name",
        ),
        sa.CheckConstraint(
            "duration_seconds BETWEEN 0 AND 86400",
            name="ck_alert_rules_duration",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_alert_rules_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "id", name="pk_alert_rules"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_alert_rules_organization_name"
        ),
    )

    op.create_table(
        "alerts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", alert_severity_enum, nullable=False),
        sa.Column(
            "status",
            alert_status_enum,
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(message)) BETWEEN 1 AND 500",
            name="ck_alerts_message",
        ),
        sa.CheckConstraint(
            "(status = 'RESOLVED') = (resolved_at IS NOT NULL)",
            name="ck_alerts_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "alert_rule_id"],
            ["alert_rules.organization_id", "alert_rules.id"],
            name="fk_alerts_rule",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_alerts_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "id", name="pk_alerts"),
    )
    op.create_index(
        "ix_alerts_status_triggered_at",
        "alerts",
        ["organization_id", "status", "triggered_at"],
    )
    op.create_index(
        "uq_alerts_active_rule_device",
        "alerts",
        ["organization_id", "alert_rule_id", "device_id"],
        unique=True,
        postgresql_where=sa.text(
            "alert_rule_id IS NOT NULL "
            "AND status IN ('OPEN', 'ACKNOWLEDGED', 'SUPPRESSED')"
        ),
    )

    op.execute(
        """
        ALTER TABLE public.metric_batches ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.metric_batches FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.metric_samples ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.metric_samples FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.alert_rules ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.alert_rules FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.alerts FORCE ROW LEVEL SECURITY;

        CREATE POLICY metric_batches_tenant_select ON public.metric_batches
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY metric_batches_tenant_insert ON public.metric_batches
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY metric_batches_tenant_update ON public.metric_batches
            FOR UPDATE TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        CREATE POLICY metric_samples_tenant_select ON public.metric_samples
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY metric_samples_tenant_insert ON public.metric_samples
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());

        CREATE POLICY alert_rules_tenant_select ON public.alert_rules
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY alert_rules_tenant_insert ON public.alert_rules
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY alert_rules_tenant_update ON public.alert_rules
            FOR UPDATE TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY alert_rules_tenant_delete ON public.alert_rules
            FOR DELETE TO nexus_app_user
            USING (organization_id = public.current_organization_id());

        CREATE POLICY alerts_tenant_select ON public.alerts
            FOR SELECT TO nexus_app_user
            USING (organization_id = public.current_organization_id());
        CREATE POLICY alerts_tenant_insert ON public.alerts
            FOR INSERT TO nexus_app_user
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY alerts_tenant_update ON public.alerts
            FOR UPDATE TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        REVOKE ALL ON TABLE public.metric_batches FROM PUBLIC;
        REVOKE ALL ON TABLE public.metric_samples FROM PUBLIC;
        REVOKE ALL ON TABLE public.metric_samples_default FROM PUBLIC;
        REVOKE ALL ON TABLE public.alert_rules FROM PUBLIC;
        REVOKE ALL ON TABLE public.alerts FROM PUBLIC;

        GRANT SELECT, INSERT, UPDATE ON TABLE public.metric_batches TO nexus_app_user;
        GRANT SELECT, INSERT ON TABLE public.metric_samples TO nexus_app_user;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.alert_rules TO nexus_app_user;
        GRANT SELECT, INSERT, UPDATE ON TABLE public.alerts TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_table("metric_samples")
    op.drop_table("metric_batches")
    op.execute(
        """
        DROP TYPE alert_status_enum;
        DROP TYPE alert_severity_enum;
        DROP TYPE comparison_operator_enum;
        DROP TYPE batch_status_enum;
        """
    )
    op.execute("RESET ROLE")
