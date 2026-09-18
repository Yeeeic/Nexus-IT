#!/usr/bin/env bash
# Exit 0 OK, 1 warning, 2 critical for WAL archive delay.
set -Eeuo pipefail

: "${NEXUS_POSTGRES_HOST:?NEXUS_POSTGRES_HOST is required}"
: "${NEXUS_POSTGRES_PORT:=5432}"
: "${NEXUS_POSTGRES_DB:=postgres}"
: "${NEXUS_POSTGRES_USER:?NEXUS_POSTGRES_USER is required}"
: "${NEXUS_POSTGRES_PASSWORD:?NEXUS_POSTGRES_PASSWORD is required}"
: "${NEXUS_WAL_WARNING_SECONDS:=600}"
: "${NEXUS_WAL_CRITICAL_SECONDS:=900}"
export PGPASSWORD="${NEXUS_POSTGRES_PASSWORD}"
trap 'unset PGPASSWORD' EXIT
if ! [[ "${NEXUS_WAL_WARNING_SECONDS}" =~ ^[0-9]{1,9}$ &&
        "${NEXUS_WAL_CRITICAL_SECONDS}" =~ ^[0-9]{1,9}$ ]] ||
   (( 10#${NEXUS_WAL_WARNING_SECONDS} < 1 ||
      10#${NEXUS_WAL_WARNING_SECONDS} >= 10#${NEXUS_WAL_CRITICAL_SECONDS} )); then
  echo "CRITICAL invalid WAL archive thresholds"; exit 2
fi
# pg_stat_archiver timestamps do not measure the backlog: idle databases may
# have an old success and every retry updates last_failed_time. PostgreSQL's
# .ready marker instead retains the time that a completed WAL entered the queue.
# missing_ok handles a marker concurrently renamed to .done by the archiver.
# The monitoring connection requires server-file read privileges, never the
# application role. This measures completed segments; archive_timeout must
# separately bound the time spent in the current, incomplete segment.
if ! lag_seconds="$(psql \
  --host="${NEXUS_POSTGRES_HOST}" --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" --dbname="${NEXUS_POSTGRES_DB}" \
  --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
  --command="SELECT CASE
    WHEN current_setting('archive_mode') = 'off' OR pg_is_in_recovery()
      THEN 2147483647
    ELSE COALESCE(GREATEST(0, FLOOR(EXTRACT(EPOCH FROM
      clock_timestamp() - MIN((pg_stat_file(
        'pg_wal/archive_status/' || name, true)).modification))))::bigint, 0)
  END
  FROM pg_ls_dir('pg_wal/archive_status') AS files(name)
  WHERE name LIKE '%.ready';")"; then
  echo "CRITICAL cannot inspect WAL archive backlog"; exit 2
fi
unset PGPASSWORD
case "${lag_seconds}" in *[!0-9]*|"") exit 2 ;; esac
if (( lag_seconds >= 10#${NEXUS_WAL_CRITICAL_SECONDS} )); then
  echo "CRITICAL WAL archive lag ${lag_seconds}s"; exit 2
fi
if (( lag_seconds >= 10#${NEXUS_WAL_WARNING_SECONDS} )); then
  echo "WARNING WAL archive lag ${lag_seconds}s"; exit 1
fi
echo "OK WAL archive lag ${lag_seconds}s"
