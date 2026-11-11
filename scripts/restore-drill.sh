#!/usr/bin/env bash
# Proves a backup is usable: restores into a throw-away PostgreSQL container, runs consistency SQL, reports timing.
# Usage: scripts/restore-drill.sh /var/backups/duale/<timestamp>
set -euo pipefail
B="${1:?backup directory}"
( cd "$B" && sha256sum -c SHA256SUMS )
NAME="duale-restore-drill-$$"; START=$(date +%s)
docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=duale postgres:16 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
until docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec -i "$NAME" pg_restore -U postgres -d duale --no-owner --exit-on-error < "$B/db.dump"
Q() { docker exec "$NAME" psql -U postgres -d duale -tA -c "$1"; }
fail=0
check() { local v; v=$(Q "$2"); if [ "$v" != "$3" ]; then echo "FAIL $1: got '$v', expected '$3'"; fail=1; else echo "ok   $1"; fi; }
check "ledger postings balance" 'SELECT count(*) FROM (SELECT "CompanyId","TxnKey","Currency" FROM "LedgerEntries" GROUP BY 1,2,3 HAVING sum("Debit")<>sum("Credit")) x' 0
check "no job has two live assignments" 'SELECT count(*) FROM (SELECT "JobId" FROM "Assignments" WHERE "Status" IN ('"'Offered','Accepted'"') GROUP BY 1 HAVING count(*)>1) x' 0
check "no orphaned payments" 'SELECT count(*) FROM "PaymentRecords" p LEFT JOIN "Companies" c ON c."Id"=p."CompanyId" WHERE c."Id" IS NULL' 0
check "confirmed payments have postings" 'SELECT count(*) FROM "PaymentRecords" p WHERE "Status"='"'Confirmed'"' AND "Kind"<>'"'direct_customer_to_technician'"' AND NOT EXISTS (SELECT 1 FROM "LedgerEntries" l WHERE l."TxnKey"='"'pay-confirm:'"'||p."Id")' 0
echo "tables restored: $(Q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")   rows in AuditEvents: $(Q 'SELECT count(*) FROM "AuditEvents"')"
echo "restore took $(( $(date +%s) - START ))s  (compare with the 4-hour RTO; record the result in docs/ops/restore-drills.md)"
if [ -f "$B/files.tar.gz" ]; then tar -tzf "$B/files.tar.gz" >/dev/null && echo "ok   files archive readable"; fi
exit $fail
