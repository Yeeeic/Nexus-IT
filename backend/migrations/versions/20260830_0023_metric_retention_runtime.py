"""Schedule-safe metric retention and aggregate intervals.

Revision ID: 20260830_0023
Revises: 20260830_0022
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260830_0023"
down_revision: str | None = "20260830_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = 'nexus_metrics_maintenance'
            ) THEN
                CREATE ROLE nexus_metrics_maintenance
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOBYPASSRLS;
            END IF;
            ALTER ROLE nexus_metrics_maintenance
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOBYPASSRLS;
        END
        $roles$;
        """
    )
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        ALTER TABLE public.metric_aggregates
            DROP CONSTRAINT pk_metric_aggregates;
        ALTER TABLE public.metric_aggregates
            ADD CONSTRAINT pk_metric_aggregates PRIMARY KEY (
                organization_id, device_id, metric_name,
                bucket_interval_seconds, bucket_start
            );

        CREATE FUNCTION public.run_metric_maintenance()
        RETURNS TABLE (
            raw_samples_deleted bigint,
            hourly_aggregates_deleted bigint,
            daily_aggregates_deleted bigint,
            partitions_dropped integer
        )
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            current_utc_date date := (clock_timestamp() AT TIME ZONE 'UTC')::date;
            partition_date date;
            partition_record record;
            tenant_record record;
            partition_identifier text;
            offset_days integer;
            affected integer;
            tenant_raw bigint;
            tenant_hourly bigint;
            tenant_daily bigint;
        BEGIN
            IF NOT pg_try_advisory_xact_lock(1314084173, 1296389187) THEN
                raw_samples_deleted := 0;
                hourly_aggregates_deleted := 0;
                daily_aggregates_deleted := 0;
                partitions_dropped := 0;
                RETURN NEXT;
                RETURN;
            END IF;

            raw_samples_deleted := 0;
            hourly_aggregates_deleted := 0;
            daily_aggregates_deleted := 0;
            partitions_dropped := 0;

            IF EXISTS (
                SELECT 1
                FROM generate_series(-14, 14) AS candidate(offset_days)
                WHERE to_regclass(format(
                    'public.metric_samples_%s',
                    to_char(current_utc_date + candidate.offset_days, 'YYYY_MM_DD')
                )) IS NULL
            ) THEN
                LOCK TABLE public.metric_samples_default IN ACCESS EXCLUSIVE MODE;
            END IF;

            FOR offset_days IN -14..14 LOOP
                partition_date := current_utc_date + offset_days;
                partition_identifier := format(
                    'metric_samples_%s', to_char(partition_date, 'YYYY_MM_DD')
                );
                IF to_regclass(format('public.%I', partition_identifier)) IS NULL THEN
                    EXECUTE format(
                        'CREATE TABLE public.%I '
                        '(LIKE public.metric_samples INCLUDING ALL)',
                        partition_identifier
                    );
                    FOR tenant_record IN
                        SELECT id FROM public.organizations ORDER BY id
                    LOOP
                        PERFORM set_config(
                            'app.current_organization_id',
                            tenant_record.id::text,
                            true
                        );
                        EXECUTE format(
                            'WITH moved AS ('
                            'DELETE FROM public.metric_samples_default '
                            'WHERE organization_id = $1 '
                            'AND recorded_at >= $2 AND recorded_at < $3 '
                            'RETURNING *'
                            ') INSERT INTO public.%I SELECT * FROM moved',
                            partition_identifier
                        ) USING
                            tenant_record.id,
                            partition_date::timestamp AT TIME ZONE 'UTC',
                            (partition_date + 1)::timestamp AT TIME ZONE 'UTC';
                    END LOOP;
                    EXECUTE format(
                        'ALTER TABLE public.metric_samples '
                        'ATTACH PARTITION public.%I '
                        'FOR VALUES FROM (%L) TO (%L)',
                        partition_identifier,
                        partition_date::timestamp AT TIME ZONE 'UTC',
                        (partition_date + 1)::timestamp AT TIME ZONE 'UTC'
                    );
                END IF;
            END LOOP;

            FOR partition_record IN
                SELECT child.relname
                FROM pg_catalog.pg_class AS child
                JOIN pg_catalog.pg_inherits AS inheritance
                  ON child.oid = inheritance.inhrelid
                JOIN pg_catalog.pg_class AS parent
                  ON parent.oid = inheritance.inhparent
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = child.relnamespace
                WHERE parent.relname = 'metric_samples'
                  AND namespace.nspname = 'public'
                  AND child.relname ~ '^metric_samples_[0-9]{4}_[0-9]{2}_[0-9]{2}$'
            LOOP
                partition_date := to_date(
                    substring(partition_record.relname FROM 16),
                    'YYYY_MM_DD'
                );
                IF partition_date < current_utc_date - 14 THEN
                    EXECUTE format(
                        'DROP TABLE IF EXISTS public.%I',
                        partition_record.relname
                    );
                    partitions_dropped := partitions_dropped + 1;
                END IF;
            END LOOP;

            FOR tenant_record IN
                SELECT id FROM public.organizations ORDER BY id
            LOOP
                PERFORM set_config(
                    'app.current_organization_id', tenant_record.id::text, true
                );
                DELETE FROM public.metric_samples
                WHERE organization_id = tenant_record.id
                  AND recorded_at < current_utc_date - INTERVAL '14 days';
                GET DIAGNOSTICS affected = ROW_COUNT;
                tenant_raw := affected;
                raw_samples_deleted := raw_samples_deleted + affected;

                DELETE FROM public.metric_aggregates
                WHERE organization_id = tenant_record.id
                  AND bucket_interval_seconds = 3600
                  AND bucket_start < current_utc_date - INTERVAL '90 days';
                GET DIAGNOSTICS affected = ROW_COUNT;
                tenant_hourly := affected;
                hourly_aggregates_deleted :=
                    hourly_aggregates_deleted + affected;

                DELETE FROM public.metric_aggregates
                WHERE organization_id = tenant_record.id
                  AND bucket_interval_seconds = 86400
                  AND bucket_start < current_utc_date - INTERVAL '365 days';
                GET DIAGNOSTICS affected = ROW_COUNT;
                tenant_daily := affected;
                daily_aggregates_deleted := daily_aggregates_deleted + affected;

                INSERT INTO public.audit_logs (
                    id, organization_id, actor_id, actor_type, action,
                    resource_type, resource_id, status, details
                ) VALUES (
                    gen_random_uuid(), tenant_record.id, NULL, 'SYSTEM',
                    'METRICS.RETENTION_PURGE', 'metrics_maintenance', NULL,
                    'SUCCESS',
                    jsonb_build_object(
                        'raw_retention_days', 14,
                        'hourly_retention_days', 90,
                        'daily_retention_days', 365,
                        'raw_samples_deleted', tenant_raw,
                        'hourly_aggregates_deleted', tenant_hourly,
                        'daily_aggregates_deleted', tenant_daily,
                        'global_partitions_dropped', partitions_dropped
                    )
                );
            END LOOP;

            RETURN NEXT;
        END
        $function$;

        REVOKE ALL ON FUNCTION public.run_metric_maintenance() FROM PUBLIC;
        GRANT USAGE ON SCHEMA public TO nexus_metrics_maintenance;
        GRANT EXECUTE ON FUNCTION public.run_metric_maintenance()
            TO nexus_metrics_maintenance;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE nexus_admin")
    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION public.run_metric_maintenance()
            FROM nexus_metrics_maintenance;
        REVOKE USAGE ON SCHEMA public FROM nexus_metrics_maintenance;
        DROP FUNCTION public.run_metric_maintenance();

        DELETE FROM public.metric_aggregates AS daily
        USING public.metric_aggregates AS hourly
        WHERE daily.bucket_interval_seconds = 86400
          AND hourly.bucket_interval_seconds = 3600
          AND daily.organization_id = hourly.organization_id
          AND daily.device_id = hourly.device_id
          AND daily.metric_name = hourly.metric_name
          AND daily.bucket_start = hourly.bucket_start;

        ALTER TABLE public.metric_aggregates
            DROP CONSTRAINT pk_metric_aggregates;
        ALTER TABLE public.metric_aggregates
            ADD CONSTRAINT pk_metric_aggregates PRIMARY KEY (
                organization_id, device_id, metric_name, bucket_start
            );
        """
    )
    op.execute("RESET ROLE")
