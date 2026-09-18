#!/usr/bin/env bash
# Prepare an empty, isolated PGDATA for point-in-time recovery.
set -Eeuo pipefail
umask 077

: "${NEXUS_PITR_TEST_ID:?NEXUS_PITR_TEST_ID is required}"
: "${BASE_BACKUP_CMS:?BASE_BACKUP_CMS is required}"
: "${BACKUP_RECIPIENT_CERT:?BACKUP_RECIPIENT_CERT is required}"
: "${BACKUP_RECIPIENT_KEY:?BACKUP_RECIPIENT_KEY is required}"
: "${RECOVERY_TARGET_TIME:?RECOVERY_TARGET_TIME is required}"
case "${NEXUS_PITR_TEST_ID}" in
  nexus-pitr-test-[a-zA-Z0-9-]*) ;;
  *) echo "[PITR-RESTORE] Identifier must start with nexus-pitr-test-" >&2; exit 2 ;;
esac
if [[ ! "${RECOVERY_TARGET_TIME}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
  || ! date -u -d "${RECOVERY_TARGET_TIME}" +%s >/dev/null 2>&1; then
  echo "[PITR-RESTORE] RECOVERY_TARGET_TIME must be valid YYYY-MM-DDTHH:MM:SSZ" >&2
  exit 2
fi
recovery_target_time_pg="$(date -u -d "${RECOVERY_TARGET_TIME}" +"%Y-%m-%d %H:%M:%S+00")"

pitr_root="/var/lib/postgresql/pitr-test/${NEXUS_PITR_TEST_ID}"
: "${PGDATA:=${pitr_root}/data}"
resolved_root="$(realpath -m -- "${pitr_root}")"
resolved_pgdata="$(realpath -m -- "${PGDATA}")"
if [ "${resolved_pgdata}" != "${resolved_root}/data" ]; then
  echo "[PITR-RESTORE] PGDATA is outside isolated PITR root" >&2
  exit 2
fi
if [ -L "${pitr_root}" ] || [ -L "${PGDATA}" ]; then
  echo "[PITR-RESTORE] Symlink targets are forbidden" >&2
  exit 2
fi
if [ -e "${PGDATA}" ] && [ -n "$(find "${PGDATA}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  echo "[PITR-RESTORE] Refusing non-empty PGDATA" >&2
  exit 2
fi

mkdir -p -- "${pitr_root}"
stage="${resolved_root}/data.stage.$$"
[ ! -e "${stage}" ] || { echo "[PITR-RESTORE] Staging path exists" >&2; exit 2; }
mkdir -- "${stage}"
chmod 700 -- "${stage}"
cleanup() {
  if [ -d "${stage}" ]; then
    find "${stage}" -mindepth 1 -delete
    rmdir -- "${stage}"
  fi
}
trap cleanup EXIT HUP INT TERM

# This script must run as the unprivileged postgres account. The caller copies
# the recipient key into the isolated restore root before invoking it.
openssl cms -decrypt -binary -inform PEM \
  -in "${BASE_BACKUP_CMS}" -recip "${BACKUP_RECIPIENT_CERT}" \
  -inkey "${BACKUP_RECIPIENT_KEY}" \
  | tar -xf - -C "${stage}"
pg_verifybackup "${stage}"
test -f "${stage}/PG_VERSION"
test "$(cat "${stage}/PG_VERSION")" = "16"
cat >> "${stage}/postgresql.auto.conf" <<EOF
restore_command = '/usr/bin/env bash /opt/nexus/pitr-restore-wal.sh %f %p'
recovery_target_time = '${recovery_target_time_pg}'
recovery_target_timeline = 'latest'
recovery_target_inclusive = on
recovery_target_action = 'pause'
archive_mode = off
EOF
touch "${stage}/recovery.signal"
if [ -e "${PGDATA}" ]; then rmdir -- "${PGDATA}"; fi
if id postgres >/dev/null 2>&1; then
  chown -R postgres:postgres -- "${stage}"
fi
mv -- "${stage}" "${PGDATA}"
trap - EXIT HUP INT TERM
echo "[PITR-RESTORE] Isolated recovery data prepared: ${PGDATA}"
