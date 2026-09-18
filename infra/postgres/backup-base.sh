#!/usr/bin/env bash
# Stream a single-tablespace physical base backup into CMS AES-256-GCM.
set -Eeuo pipefail
umask 077

: "${NEXUS_POSTGRES_HOST:?NEXUS_POSTGRES_HOST is required}"
: "${NEXUS_POSTGRES_PORT:=5432}"
: "${NEXUS_POSTGRES_USER:?NEXUS_POSTGRES_USER is required}"
: "${NEXUS_POSTGRES_PASSWORD:?NEXUS_POSTGRES_PASSWORD is required}"
: "${BACKUP_OUTPUT_DIR:=/var/backups/nexus}"
: "${BASE_BACKUP_OUTPUT_FILE:=${BACKUP_OUTPUT_DIR}/base_$(date -u +"%Y%m%d_%H%M%SZ").tar.cms}"
: "${BACKUP_RECIPIENT_CERT:?BACKUP_RECIPIENT_CERT is required}"

temporary="${BASE_BACKUP_OUTPUT_FILE}.tmp.$$"
cleanup() {
  rm -f -- "${temporary}"
  unset PGPASSWORD
}
trap cleanup EXIT HUP INT TERM

output_dir="$(dirname -- "${BASE_BACKUP_OUTPUT_FILE}")"
mkdir -p -- "${output_dir}"
chmod 700 -- "${output_dir}"
openssl x509 -in "${BACKUP_RECIPIENT_CERT}" -noout -checkend 0 >/dev/null
export PGPASSWORD="${NEXUS_POSTGRES_PASSWORD}"

extra_tablespaces="$(psql \
  --host="${NEXUS_POSTGRES_HOST}" --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" --dbname=postgres \
  --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
  --command="SELECT count(*) FROM pg_tablespace WHERE spcname NOT IN ('pg_default', 'pg_global');")"
if [ "${extra_tablespaces}" != "0" ]; then
  echo "[PITR-BACKUP] Streaming backup refuses additional tablespaces" >&2
  exit 2
fi

pg_basebackup \
  --host="${NEXUS_POSTGRES_HOST}" --port="${NEXUS_POSTGRES_PORT}" \
  --username="${NEXUS_POSTGRES_USER}" --no-password \
  --checkpoint=fast --format=tar --wal-method=fetch \
  --manifest-checksums=SHA256 \
  --label="nexus-pitr-$(date -u +"%Y%m%d_%H%M%SZ")" \
  --pgdata=- \
  | openssl cms -encrypt -aes-256-gcm -binary -stream -outform PEM \
      -out "${temporary}" "${BACKUP_RECIPIENT_CERT}"

chmod 600 -- "${temporary}"
mv -- "${temporary}" "${BASE_BACKUP_OUTPUT_FILE}"
sha256sum -- "${BASE_BACKUP_OUTPUT_FILE}" > "${BASE_BACKUP_OUTPUT_FILE}.sha256"
chmod 600 -- "${BASE_BACKUP_OUTPUT_FILE}.sha256"
echo "[PITR-BACKUP] Authenticated base backup completed: ${BASE_BACKUP_OUTPUT_FILE}"
