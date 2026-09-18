#!/usr/bin/env bash
# Destructive only inside a uniquely named Compose project created here.
set -Eeuo pipefail
umask 077

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repository_root}/infra/compose.pitr-test.yaml"
project="nexus-pitr-test-$(openssl rand -hex 8)"
case "${project}" in
  nexus-pitr-test-[a-f0-9][a-f0-9]*) ;;
  *) echo "Refusing unsafe Compose project: ${project}" >&2; exit 2 ;;
esac
if [ "${project}" = "nexus-it" ] || [ "${project}_postgres_data" = "nexus-it_postgres_data" ]; then
  echo "Refusing unsafe Compose project: ${project}" >&2
  exit 2
fi

key_dir="$(mktemp -d)"
export NEXUS_PITR_KEY_DIR="${key_dir}"
export NEXUS_PITR_PASSWORD="$(openssl rand -hex 32)"
export NEXUS_PITR_TEST_ID="${project}"
compose=(docker compose -p "${project}" -f "${compose_file}")

cleanup() {
  status=$?
  if [ "${status}" -ne 0 ]; then
    "${compose[@]}" logs --no-color 2>/dev/null || true
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "${key_dir}"
  return "${status}"
}
trap cleanup EXIT HUP INT TERM

openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 2 \
  -subj "/CN=NEXUS PITR isolated rehearsal" \
  -keyout "${key_dir}/recipient.key" -out "${key_dir}/recipient.crt" >/dev/null 2>&1
chmod 600 "${key_dir}/recipient.key"
chmod 644 "${key_dir}/recipient.crt"

"${compose[@]}" up --detach --wait source
"${compose[@]}" exec -T source psql -U nexus_pitr -d nexus_pitr -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE pitr_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE TABLE pitr_parent (
  organization_id uuid NOT NULL,
  id integer NOT NULL,
  PRIMARY KEY (organization_id, id)
);
CREATE TABLE pitr_sentinel (
  id integer PRIMARY KEY,
  organization_id uuid NOT NULL,
  parent_id integer NOT NULL,
  marker text NOT NULL
);
ALTER TABLE pitr_sentinel ADD CONSTRAINT pitr_sentinel_parent_fk
  FOREIGN KEY (organization_id, parent_id)
  REFERENCES pitr_parent (organization_id, id);
ALTER TABLE pitr_sentinel ENABLE ROW LEVEL SECURITY;
ALTER TABLE pitr_sentinel FORCE ROW LEVEL SECURITY;
CREATE POLICY pitr_sentinel_tenant ON pitr_sentinel
  USING (organization_id = current_setting('app.current_organization_id')::uuid);
GRANT USAGE ON SCHEMA public TO pitr_runtime;
GRANT SELECT ON pitr_sentinel TO pitr_runtime;
INSERT INTO pitr_parent VALUES
  ('00000000-0000-0000-0000-000000000001', 1),
  ('00000000-0000-0000-0000-000000000002', 1);
SQL
"${compose[@]}" --profile tools run --rm base-backup
"${compose[@]}" exec -T source psql -U nexus_pitr -d nexus_pitr -v ON_ERROR_STOP=1 \
  -c "INSERT INTO pitr_sentinel VALUES (1, '00000000-0000-0000-0000-000000000001', 1, 'before-target'), (3, '00000000-0000-0000-0000-000000000002', 1, 'other-tenant');"
archived_before="$(${compose[@]} exec -T source psql -U nexus_pitr -d nexus_pitr -At -c "SELECT archived_count FROM pg_stat_archiver;")"
sleep 2
export RECOVERY_TARGET_TIME
RECOVERY_TARGET_TIME="$("${compose[@]}" exec -T source psql -U nexus_pitr -d nexus_pitr -At \
  -c "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"');")"
sleep 2
"${compose[@]}" exec -T source psql -U nexus_pitr -d nexus_pitr -v ON_ERROR_STOP=1 \
  -c "INSERT INTO pitr_sentinel VALUES (2, '00000000-0000-0000-0000-000000000001', 1, 'after-target'); SELECT pg_switch_wal();"

for _ in $(seq 1 30); do
  archived="$("${compose[@]}" exec -T source psql -U nexus_pitr -d nexus_pitr -At -c "SELECT archived_count FROM pg_stat_archiver;")"
  [ "${archived}" -gt "${archived_before}" ] && break
  sleep 1
done
[ "${archived:-0}" -gt "${archived_before}" ] || { echo "No new WAL segment archived" >&2; exit 1; }
"${compose[@]}" exec -T \
  -e NEXUS_POSTGRES_HOST=127.0.0.1 \
  -e NEXUS_POSTGRES_USER=nexus_pitr \
  -e NEXUS_POSTGRES_PASSWORD="${NEXUS_PITR_PASSWORD}" \
  source bash /opt/nexus/pitr-check-archive-lag.sh >/dev/null

started="$(date +%s)"
"${compose[@]}" --profile tools run --rm restore-prepare
"${compose[@]}" up --detach --wait restored
rto_seconds="$(( $(date +%s) - started ))"
[ "${rto_seconds}" -le 14400 ] || { echo "RTO exceeded: ${rto_seconds}s" >&2; exit 1; }
rpo_seconds="$(( $(date -u +%s) - $(date -u -d "${RECOVERY_TARGET_TIME}" +%s) ))"
[ "${rpo_seconds}" -le 3600 ] || { echo "RPO exceeded: ${rpo_seconds}s" >&2; exit 1; }

rows="$("${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -At \
  -c "SELECT string_agg(id::text, ',' ORDER BY id) FROM pitr_sentinel;")"
[ "${rows}" = "1,3" ] || { echo "Unexpected restored sentinels: ${rows}" >&2; exit 1; }
tenant_one="$("${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -qAt \
  -c "SET ROLE pitr_runtime; SET app.current_organization_id = '00000000-0000-0000-0000-000000000001'; SELECT string_agg(id::text, ',' ORDER BY id) FROM pitr_sentinel;")"
[ "${tenant_one}" = "1" ] || { echo "RLS tenant isolation failed" >&2; exit 1; }
fk_valid="$("${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -At \
  -c "SELECT convalidated FROM pg_constraint WHERE conname = 'pitr_sentinel_parent_fk';")"
[ "${fk_valid}" = "t" ] || { echo "Composite FK missing or invalid" >&2; exit 1; }
role_flags="$("${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -At \
  -c "SELECT rolsuper::text || ':' || rolbypassrls::text FROM pg_roles WHERE rolname = 'pitr_runtime';")"
[ "${role_flags}" = "false:false" ] || { echo "Restored runtime role is privileged" >&2; exit 1; }
recovery="$("${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -At -c "SELECT pg_is_in_recovery();")"
[ "${recovery}" = "t" ] || { echo "Recovery did not pause at target" >&2; exit 1; }
"${compose[@]}" exec -T restored psql -U nexus_pitr -d nexus_pitr -v ON_ERROR_STOP=1 \
  -c "SELECT pg_wal_replay_resume();" >/dev/null

echo "PITR rehearsal passed; target=${RECOVERY_TARGET_TIME}; RPO=${rpo_seconds}s; RTO=${rto_seconds}s"
