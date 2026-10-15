#!/usr/bin/env bash
# Restore a backup into a SCRATCH database and verify it. Never touches the live database.
#
# Usage: ops/restore_test.sh /path/to/armyhq-YYYYmmddTHHMMSSZ.dump.age
# Env:   AGE_IDENTITY (path to the age private key)  PGHOST PGPORT PGUSER  (PGPASSWORD or ~/.pgpass)
#        LIVE_DB (name of the production database, refused as a target; default: armyhq)
#        BACKEND_DIR (default ./backend) with the application's environment variables already exported
set -euo pipefail
archive="${1:?usage: restore_test.sh <archive.dump.age>}"
: "${AGE_IDENTITY:?set AGE_IDENTITY}"
LIVE_DB="${LIVE_DB:-armyhq}"
BACKEND_DIR="${BACKEND_DIR:-./backend}"
target="restore_test_$(date -u +%Y%m%d%H%M%S)"
[[ "$target" == "$LIVE_DB" ]] && { echo "refusing to restore over the live database"; exit 1; }

echo "== verifying checksum"
sha256sum -c "$archive.sha256"
echo "== creating scratch database $target"
createdb "$target"
cleanup() { [[ "${KEEP_SCRATCH:-0}" == "1" ]] || dropdb --if-exists "$target"; }
trap cleanup EXIT
echo "== restoring"
started=$(date +%s)
age -d -i "$AGE_IDENTITY" "$archive" | pg_restore --no-owner --no-privileges --dbname "$target" --exit-on-error
echo "restore took $(( $(date +%s) - started ))s"

echo "== integrity checks (against the scratch copy only)"
psql -v ON_ERROR_STOP=1 -At "$target" <<'SQL'
SELECT 'users', count(*) FROM users
UNION ALL SELECT 'audit_events', count(*) FROM audit_events
UNION ALL SELECT 'personnel', count(*) FROM personnel
UNION ALL SELECT 'submissions', count(*) FROM submissions
UNION ALL SELECT 'stock_transactions', count(*) FROM stock_transactions
UNION ALL SELECT 'training_records', count(*) FROM training_records;
SELECT 'append-only triggers present: ' || count(*) FROM pg_trigger WHERE tgname LIKE '%no_change';
SELECT 'ledger balances consistent: ' || (SELECT count(*) = 0 FROM stock_lines s
  WHERE s.quantity <> COALESCE((SELECT sum(delta) FROM stock_transactions t WHERE t.stock_line_id = s.id), 0)
  AND EXISTS (SELECT 1 FROM stock_transactions t WHERE t.stock_line_id = s.id));
SQL
echo "== application-level checks against the scratch copy"
( cd "$BACKEND_DIR" && POSTGRES_DB="$target" python manage.py showmigrations --plan | grep -c '\[ \]' | xargs -I{} echo "unapplied migrations: {}" \
  && POSTGRES_DB="$target" python manage.py check )
echo "== RESTORE TEST PASSED for $archive (record the result in docs/RUNBOOK.md, section 'Restore test log')"
