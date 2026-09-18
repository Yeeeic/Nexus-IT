#!/bin/sh
set -eu

: "${NEXUS_POSTGRES_HOST:?required}"
: "${NEXUS_POSTGRES_PORT:?required}"
: "${NEXUS_POSTGRES_DB:?required}"
: "${NEXUS_POSTGRES_USER:?required}"
: "${NEXUS_POSTGRES_PASSWORD:?required}"
: "${NEXUS_RUNTIME_POSTGRES_PASSWORD:?required}"
: "${NEXUS_MAINTENANCE_POSTGRES_PASSWORD:?required}"

export PGPASSWORD="${NEXUS_POSTGRES_PASSWORD}"

psql \
  --host="${NEXUS_POSTGRES_HOST}" \
  --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" \
  --dbname="${NEXUS_POSTGRES_DB}" \
  --no-psqlrc \
  --set=ON_ERROR_STOP=1 \
  --set=runtime_password="${NEXUS_RUNTIME_POSTGRES_PASSWORD}" \
  --set=maintenance_password="${NEXUS_MAINTENANCE_POSTGRES_PASSWORD}" <<'SQL'
SELECT format(
  'CREATE ROLE nexus_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'runtime_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'nexus_runtime'
)
\gexec

SELECT format(
  'ALTER ROLE nexus_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'runtime_password'
)
\gexec

GRANT nexus_auth_user, nexus_app_user TO nexus_runtime;

SELECT format(
  'CREATE ROLE nexus_maintenance_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'maintenance_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'nexus_maintenance_runtime'
)
\gexec

SELECT format(
  'ALTER ROLE nexus_maintenance_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'maintenance_password'
)
\gexec

GRANT nexus_app_user, nexus_metrics_maintenance TO nexus_maintenance_runtime;
SQL

unset PGPASSWORD
