#!/usr/bin/env bash
# Stream logical PostgreSQL backups into CMS AES-256-GCM envelopes.
set -Eeuo pipefail
umask 077

: "${NEXUS_POSTGRES_HOST:?NEXUS_POSTGRES_HOST is required}"
: "${NEXUS_POSTGRES_PORT:=5432}"
: "${NEXUS_POSTGRES_DB:?NEXUS_POSTGRES_DB is required}"
: "${NEXUS_POSTGRES_USER:?NEXUS_POSTGRES_USER is required}"
: "${NEXUS_POSTGRES_PASSWORD:?NEXUS_POSTGRES_PASSWORD is required}"
: "${BACKUP_OUTPUT_DIR:=/var/backups/nexus}"
: "${BACKUP_RECIPIENT_CERT:?BACKUP_RECIPIENT_CERT is required}"

timestamp="$(date -u +"%Y%m%d_%H%M%SZ")"
backup_dir="${BACKUP_OUTPUT_DIR}/${timestamp}"
globals_out="${backup_dir}/globals_${timestamp}.sql.cms"
database_out="${backup_dir}/db_${NEXUS_POSTGRES_DB}_${timestamp}.dump.cms"
temporary_files=()

cleanup() {
  local file
  for file in "${temporary_files[@]:-}"; do
    [ -n "${file}" ] && rm -f -- "${file}"
  done
  unset PGPASSWORD
}
trap cleanup EXIT HUP INT TERM

openssl x509 -in "${BACKUP_RECIPIENT_CERT}" -noout -checkend 0 >/dev/null
mkdir -p -- "${backup_dir}"
chmod 700 -- "${backup_dir}"
export PGPASSWORD="${NEXUS_POSTGRES_PASSWORD}"

encrypt_to() {
  local output="$1"
  local temporary="${output}.tmp.$$"
  temporary_files+=("${temporary}")
  openssl cms -encrypt -aes-256-gcm -binary -stream -outform PEM \
    -out "${temporary}" "${BACKUP_RECIPIENT_CERT}"
  chmod 600 -- "${temporary}"
  mv -- "${temporary}" "${output}"
}

pg_dumpall \
  --host="${NEXUS_POSTGRES_HOST}" \
  --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" \
  --globals-only --no-role-passwords \
  | encrypt_to "${globals_out}"

pg_dump \
  --host="${NEXUS_POSTGRES_HOST}" \
  --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" \
  --dbname="${NEXUS_POSTGRES_DB}" \
  --format=custom --compress=6 \
  | encrypt_to "${database_out}"

(
  cd -- "${backup_dir}"
  sha256sum -- "$(basename -- "${globals_out}")" "$(basename -- "${database_out}")" > SHA256SUMS
  chmod 600 -- SHA256SUMS
)
echo "[NEXUS-BACKUP] Authenticated logical backup completed: ${backup_dir}"
