#!/usr/bin/env bash
# Encrypted PostgreSQL backup. The archive is encrypted to a PUBLIC key, so the server never holds the
# means to read old backups; keep the matching private key offline with the designated custodians.
#
# Needs: pg_dump, age (https://age-encryption.org), sha256sum.
# Env:   PGHOST PGPORT PGUSER PGDATABASE (and PGPASSWORD or ~/.pgpass)  BACKUP_DIR  AGE_RECIPIENT
set -euo pipefail
: "${PGDATABASE:?set PGDATABASE}"; : "${BACKUP_DIR:?set BACKUP_DIR}"; : "${AGE_RECIPIENT:?set AGE_RECIPIENT (age public key)}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
umask 077
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/armyhq-${stamp}.dump.age"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT
pg_dump --format=custom --no-owner --no-privileges --serializable-deferrable "$PGDATABASE" | age -r "$AGE_RECIPIENT" -o "$tmp"
mv "$tmp" "$out"
sha256sum "$out" > "$out.sha256"
echo "backup written: $out ($(stat -c %s "$out") bytes)"
# Retention: delete archives older than RETENTION_DAYS (copy off-host BEFORE relying on this).
find "$BACKUP_DIR" -maxdepth 1 -name 'armyhq-*.dump.age*' -mtime "+$RETENTION_DAYS" -print -delete
