#!/usr/bin/env bash
# restore_command helper for authenticated WAL archives.
set -Eeuo pipefail
umask 077

: "${WAL_ARCHIVE_DIR:=/var/lib/postgresql/wal_archive}"
: "${BACKUP_RECIPIENT_CERT:?BACKUP_RECIPIENT_CERT is required}"
: "${BACKUP_RECIPIENT_KEY:?BACKUP_RECIPIENT_KEY is required}"
wal_name="${1:?WAL file name is required}"
destination="${2:?WAL destination path is required}"
case "${wal_name}" in *[!A-Fa-f0-9._-]*|*/*|.|..|"") exit 2 ;; esac

archive_entry="${WAL_ARCHIVE_DIR}/${wal_name}.ready"
encrypted="${archive_entry}/segment.cms"
digest_file="${archive_entry}/segment.sha256"
[ -f "${encrypted}" ] && [ -f "${digest_file}" ] || exit 1
expected_digest="$(tr -d '[:space:]' < "${digest_file}")"
case "${expected_digest}" in *[!A-Fa-f0-9]*|"") exit 1 ;; esac
[ "${#expected_digest}" -eq 64 ] || exit 1

temporary="${destination}.tmp.$$"
cleanup() { rm -f -- "${temporary}"; }
trap cleanup EXIT HUP INT TERM
openssl cms -decrypt -binary -inform PEM \
  -in "${encrypted}" -recip "${BACKUP_RECIPIENT_CERT}" \
  -inkey "${BACKUP_RECIPIENT_KEY}" -out "${temporary}"
printf '%s  %s\n' "${expected_digest}" "${temporary}" | sha256sum --check --status
chmod 600 -- "${temporary}"
mv -- "${temporary}" "${destination}"
