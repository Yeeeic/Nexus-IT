#!/usr/bin/env bash
# archive_command helper: authenticated, atomic and conflict-detecting WAL copy.
set -Eeuo pipefail
umask 077

: "${WAL_ARCHIVE_DIR:=/var/lib/postgresql/wal_archive}"
: "${BACKUP_RECIPIENT_CERT:?BACKUP_RECIPIENT_CERT is required}"
source_path="${1:?WAL file path is required}"
wal_name="${2:?WAL file name is required}"

if [[ ! "${wal_name}" =~ ^([A-Fa-f0-9]{24}|[A-Fa-f0-9]{24}\.[A-Fa-f0-9]{8}\.backup|[A-Fa-f0-9]{8}\.history)$ ]]; then
  echo "[WAL-ARCHIVE] Invalid WAL file name" >&2
  exit 2
fi
openssl x509 -in "${BACKUP_RECIPIENT_CERT}" -noout -checkend 0 >/dev/null
mkdir -p -- "${WAL_ARCHIVE_DIR}"
chmod 700 -- "${WAL_ARCHIVE_DIR}"

destination_directory="${WAL_ARCHIVE_DIR}/${wal_name}.ready"
destination="${destination_directory}/segment.cms"
digest_file="${destination_directory}/segment.sha256"
source_digest="$(sha256sum -- "${source_path}" | awk '{print $1}')"
if [ -e "${destination_directory}" ]; then
  if [ -f "${destination}" ] && [ -f "${digest_file}" ] \
    && [ "$(tr -d '[:space:]' < "${digest_file}")" = "${source_digest}" ]; then
    exit 0
  fi
  echo "[WAL-ARCHIVE] WAL archive conflict: ${wal_name}" >&2
  exit 1
fi

temporary_directory="${WAL_ARCHIVE_DIR}/.${wal_name}.tmp.$$"
mkdir -- "${temporary_directory}"
temporary_cms="${temporary_directory}/segment.cms"
temporary_digest="${temporary_directory}/segment.sha256"
cleanup() {
  rm -f -- "${temporary_cms}" "${temporary_digest}"
  rmdir -- "${temporary_directory}" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
openssl cms -encrypt -aes-256-gcm -binary -stream -outform PEM \
  -in "${source_path}" -out "${temporary_cms}" "${BACKUP_RECIPIENT_CERT}"
printf '%s\n' "${source_digest}" > "${temporary_digest}"
chmod 600 -- "${temporary_cms}" "${temporary_digest}"
mv -T -- "${temporary_directory}" "${destination_directory}"
echo "[WAL-ARCHIVE] Archived ${wal_name}"
