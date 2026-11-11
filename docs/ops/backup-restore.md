# Backup and restore

| Target (proposed in the spec) | How it is met | Status |
|---|---|---|
| RPO ≤ 15 min | PostgreSQL WAL archiving / managed PITR on the database host | **Not configured here** — depends on the hosting decision. `scripts/backup.sh` alone gives only the interval you schedule. |
| RTO ≤ 4 h | Restore from latest dump (+WAL), re-deploy images, run integrity check | Measure with `restore-drill.sh`; record below. |

## What is backed up
Database (`pg_dump -Fc`), the private files volume (identity documents and job evidence — **sensitive**), checksums. Not backed up: `prod.env` secrets (keep them in the secret manager; **losing `Mfa__Key` disables everyone's MFA, losing `Jwt__Key` only signs people out**).
Backups must leave the host, be encrypted at rest, and be access-restricted like the production data. Retention is a business decision.

## Backup
`scripts/backup.sh` (cron, at least daily; more often once WAL archiving is configured).

## Restore (real incident)
1. Declare the incident (incident-response.md). Stop the API: `docker compose stop api`.
2. Verify the chosen backup: `cd <dir> && sha256sum -c SHA256SUMS`.
3. New database: `docker compose exec -T db psql -U postgres -c 'CREATE DATABASE duale_restore OWNER duale'`, then `pg_restore -U duale -d duale_restore --no-owner < db.dump`. For PITR follow your host's procedure to the chosen timestamp.
4. Restore files: `tar -xzf files.tar.gz -C <files volume>`.
5. Swap the database name in the connection string, start the API, wait for `/health/ready`.
6. Run `GET /platform/integrity` (must be `ok:true`) and `scripts/smoke.sh`. Compare the latest payment/ledger rows with the payment provider's reports for the gap period; anything confirmed at the provider but missing here is reconciled manually and noted on the incident.
7. Tell users about the data-loss window, if any. Notifications and idempotency keys for the gap period are gone; phones re-send queued work safely.

## Restore drill (monthly, and after every schema release)
`scripts/restore-drill.sh <backup dir>` restores into a throw-away container, checks the ledger balances, no job has two live assignments, no orphan payments, every confirmed payment has its posting, and prints the elapsed time. Record every run:

| Date | Backup | Elapsed | Result | By |
|---|---|---|---|---|
| _not yet run_ | | | | |
