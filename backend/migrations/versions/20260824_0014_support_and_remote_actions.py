"""Add tenant help desk and controlled remote action persistence.

Revision ID: 20260824_0014
Revises: 20260824_0013
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0014"
down_revision: str | None = "20260824_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "tickets",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ticket_number", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="NEW"
        ),
        sa.Column(
            "priority", sa.String(length=20), nullable=False, server_default="MEDIUM"
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('NEW','ASSIGNED','IN_PROGRESS','PENDING_CUSTOMER',"
            "'RESOLVED','CLOSED')",
            name="ck_tickets_status",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_tickets_priority",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 255",
            name="ck_tickets_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 10000",
            name="ck_tickets_description_bounded",
        ),
        sa.CheckConstraint(
            "(status IN ('RESOLVED','CLOSED')) = (resolved_at IS NOT NULL)",
            name="ck_tickets_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_tickets_device",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "alert_id"],
            ["alerts.organization_id", "alerts.id"],
            name="fk_tickets_alert",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_tickets_creator_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "assigned_to"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_tickets_assignee_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("organization_id", "id", name="pk_tickets"),
        sa.UniqueConstraint(
            "organization_id",
            "ticket_number",
            name="uq_tickets_organization_number",
        ),
    )
    op.create_index(
        "ix_tickets_organization_status_created",
        "tickets",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "ticket_comments",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_internal", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(btrim(content)) BETWEEN 1 AND 10000",
            name="ck_ticket_comments_content_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ticket_id"],
            ["tickets.organization_id", "tickets.id"],
            name="fk_ticket_comments_ticket",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_ticket_comments_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "id", name="pk_ticket_comments"
        ),
    )
    op.create_index(
        "ix_ticket_comments_ticket_created",
        "ticket_comments",
        ["organization_id", "ticket_id", "created_at"],
    )

    op.create_table(
        "ticket_attachments",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("encryption_key_id", sa.String(length=100), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "file_size BETWEEN 1 AND 10485760",
            name="ck_ticket_attachments_size",
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/png','image/jpeg','application/pdf')",
            name="ck_ticket_attachments_mime",
        ),
        sa.CheckConstraint(
            "stored_filename ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
            "[0-9a-f]{12}\\.(png|jpg|pdf)$'",
            name="ck_ticket_attachments_generated_name",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "ticket_id"],
            ["tickets.organization_id", "tickets.id"],
            name="fk_ticket_attachments_ticket",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "id", name="pk_ticket_attachments"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "stored_filename",
            name="uq_ticket_attachments_stored_filename",
        ),
    )

    op.create_table(
        "action_executions",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_name", sa.String(length=100), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nonce", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=True),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("parameters_canonical", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="DISPATCHED",
        ),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("result_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "acknowledged_token_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action_name IN ('restart_service','flush_dns',"
            "'collect_extended_diagnostics','reboot_system')",
            name="ck_action_executions_catalog",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_APPROVAL','DISPATCHED','ACCEPTED','EXECUTING',"
            "'COMPLETED','FAILED','INTERRUPTED','UNKNOWN','TIMED_OUT','REJECTED')",
            name="ck_action_executions_status",
        ),
        sa.CheckConstraint(
            "key_version IS NULL OR key_version > 0",
            name="ck_action_executions_key_version",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at AND "
            "expires_at <= issued_at + INTERVAL '5 minutes'",
            name="ck_action_executions_expiry",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object' AND "
            "pg_column_size(parameters) <= 8192",
            name="ck_action_executions_parameters",
        ),
        sa.CheckConstraint(
            "length(parameters_canonical) BETWEEN 2 AND 8192",
            name="ck_action_executions_canonical_bounded",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING_APPROVAL' AND signature IS NULL "
            "AND key_version IS NULL) OR "
            "(status <> 'PENDING_APPROVAL' AND "
            "length(signature) BETWEEN 80 AND 128 AND key_version IS NOT NULL)",
            name="ck_action_executions_signature_bounded",
        ),
        sa.CheckConstraint(
            "(approved_by IS NULL) = (approved_at IS NULL)",
            name="ck_action_executions_approval_pair",
        ),
        sa.CheckConstraint(
            "result_digest IS NULL OR octet_length(result_digest) = 32",
            name="ck_action_executions_result_digest",
        ),
        sa.CheckConstraint(
            "output_summary IS NULL OR length(output_summary) <= 2000",
            name="ck_action_executions_output_bounded",
        ),
        sa.CheckConstraint(
            "(acknowledged_token_id IS NULL) = (accepted_at IS NULL)",
            name="ck_action_executions_ack_pair",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_action_executions_device",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requested_by"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_action_executions_requester_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "approved_by"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            name="fk_action_executions_approver_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "acknowledged_token_id"],
            ["device_tokens.organization_id", "device_tokens.id"],
            name="fk_action_executions_ack_token",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "id", name="pk_action_executions"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "device_id",
            "nonce",
            name="uq_action_executions_device_nonce",
        ),
    )
    op.create_index(
        "ix_action_executions_device_status",
        "action_executions",
        ["organization_id", "device_id", "status", "issued_at"],
    )

    op.execute(
        """
        ALTER TABLE public.tickets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.tickets FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.ticket_comments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.ticket_comments FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.ticket_attachments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.ticket_attachments FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.action_executions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.action_executions FORCE ROW LEVEL SECURITY;

        CREATE POLICY tickets_tenant_all ON public.tickets
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY ticket_comments_tenant_all ON public.ticket_comments
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY ticket_attachments_tenant_all ON public.ticket_attachments
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY action_executions_tenant_all ON public.action_executions
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        REVOKE ALL ON TABLE public.tickets FROM PUBLIC;
        REVOKE ALL ON TABLE public.ticket_comments FROM PUBLIC;
        REVOKE ALL ON TABLE public.ticket_attachments FROM PUBLIC;
        REVOKE ALL ON TABLE public.action_executions FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON TABLE public.tickets TO nexus_app_user;
        GRANT SELECT, INSERT ON TABLE public.ticket_comments TO nexus_app_user;
        GRANT SELECT, INSERT, DELETE ON TABLE public.ticket_attachments TO nexus_app_user;
        GRANT SELECT, INSERT, UPDATE ON TABLE public.action_executions TO nexus_app_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("action_executions")
    op.drop_table("ticket_attachments")
    op.drop_table("ticket_comments")
    op.drop_table("tickets")
    op.execute("RESET ROLE")
