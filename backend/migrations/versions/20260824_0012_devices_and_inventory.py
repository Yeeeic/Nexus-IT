"""Add tenant devices, machine credentials, and current inventory.

Revision ID: 20260824_0012
Revises: 20260824_0011
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0012"
down_revision: str | None = "20260824_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.create_table(
        "devices",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
            "length(btrim(hostname)) BETWEEN 1 AND 255",
            name="ck_devices_hostname_not_blank",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) BETWEEN 1 AND 150",
            name="ck_devices_display_name_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_devices_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "id", name="pk_devices"),
        sa.UniqueConstraint(
            "organization_id", "hostname", name="uq_devices_organization_hostname"
        ),
    )
    op.create_index("ix_devices_organization_active", "devices", ["organization_id", "is_active"])

    op.create_table(
        "device_tokens",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_device_tokens_hash_length",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_device_tokens_expiry",
        ),
        sa.CheckConstraint(
            "(is_revoked AND revoked_at IS NOT NULL) OR "
            "(NOT is_revoked AND revoked_at IS NULL)",
            name="ck_device_tokens_revocation_state",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_device_tokens_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "id", name="pk_device_tokens"),
        sa.UniqueConstraint("id", name="uq_device_tokens_id"),
    )
    op.create_index(
        "ix_device_tokens_device_active",
        "device_tokens",
        ["organization_id", "device_id", "expires_at"],
        postgresql_where=sa.text("NOT is_revoked"),
    )

    op.create_table(
        "device_inventory",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "hardware",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "software_packages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "patches",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "services",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(hardware) = 'object' "
            "AND pg_column_size(hardware) <= 65536",
            name="ck_device_inventory_hardware_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(software_packages) = 'array' "
            "AND pg_column_size(software_packages) <= 1048576",
            name="ck_device_inventory_software_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(patches) = 'array' "
            "AND pg_column_size(patches) <= 524288",
            name="ck_device_inventory_patches_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(services) = 'array' "
            "AND pg_column_size(services) <= 524288",
            name="ck_device_inventory_services_array",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["devices.organization_id", "devices.id"],
            name="fk_device_inventory_device",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "device_id", name="pk_device_inventory"
        ),
    )

    op.execute(
        """
        ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.devices FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.device_tokens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.device_tokens FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.device_inventory ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.device_inventory FORCE ROW LEVEL SECURITY;

        CREATE POLICY devices_tenant_all ON public.devices
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY device_tokens_tenant_all ON public.device_tokens
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());
        CREATE POLICY device_tokens_auth_select ON public.device_tokens
            FOR SELECT TO nexus_auth_user
            USING (true);
        CREATE POLICY device_inventory_tenant_all ON public.device_inventory
            FOR ALL TO nexus_app_user
            USING (organization_id = public.current_organization_id())
            WITH CHECK (organization_id = public.current_organization_id());

        REVOKE ALL ON TABLE public.devices FROM PUBLIC;
        REVOKE ALL ON TABLE public.device_tokens FROM PUBLIC;
        REVOKE ALL ON TABLE public.device_inventory FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.devices TO nexus_app_user;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.device_tokens TO nexus_app_user;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.device_inventory TO nexus_app_user;
        GRANT SELECT (
            id, organization_id, device_id, token_hash, expires_at, is_revoked
        ) ON TABLE public.device_tokens TO nexus_auth_user;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.drop_table("device_inventory")
    op.drop_table("device_tokens")
    op.drop_table("devices")
    op.execute("RESET ROLE")
