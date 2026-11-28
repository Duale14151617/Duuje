# Backup and recovery

## What happens
`.github/workflows/backup.yml` runs every night (21:17 UTC, 00:17 in Garowe) and on demand:
1. dumps the production database (`pg_dump`, custom format) and refuses a dump that is suspiciously small;
2. **restores it into a throwaway PostgreSQL database and checks it** (tables, migrations, users and audit events exist), so a backup that cannot be restored fails the job and GitHub emails you. The result is also written to the run's summary page;
3. encrypts the dump to a **public** key with `age` (the repository never holds the private key, so it cannot read its own backups) and deletes the plain copy;
4. keeps the encrypted file and its checksum as a private workflow artifact for 30 days;
5. optionally refreshes a live second copy in Neon, and tells the System health page the backup ran (only after steps 1 to 4 succeeded).

Recovery point: at most 24 hours of data. Recovery time: roughly an hour, most of it spent following the steps below.

## One-time setup
1. Make an age key pair on a trusted computer: `age-keygen -o duuje-backup.key`. It prints the **public key** (`age1...`). The file holds the **private key**.
2. In Render, open the database and copy the **External Database URL**. Allow your connections to it (Render's access control list must permit GitHub's runners, or leave it open and rely on the password plus TLS).
3. GitHub repository: Settings, Secrets and variables, Actions: add `BACKUP_DATABASE_URL` and `BACKUP_AGE_RECIPIENT` (the public key). Optional: `BACKUP_NEON_URL`, `BACKUP_HEARTBEAT_URL` and `BACKUP_HEARTBEAT_TOKEN`. The repository must be private.
4. Save in your password manager: the private key file (`duuje-backup.key`), `FIELD_ENCRYPTION_KEY` (and any older key), and `FIELD_HMAC_KEY` if set. **A backup without those cannot be read.** Keep one offline copy (printed or on a USB stick) in a different place from your laptop. Never put the private key in GitHub.
5. Check `PG_VERSION` in the workflow matches the database's PostgreSQL version.
6. Run the workflow once by hand (Actions, Nightly database backup and restore test, Run workflow) and confirm it is green and the summary says "Backup restore test passed".

## Beyond 30 days
Artifacts expire. Once a month, download the newest `policehq-backup-...` artifact and keep it somewhere you control (external drive, a second cloud account). It is encrypted, so storage can be untrusted. Also turn on Render's own database backups if your plan has them: two independent copies.

## Restore (disaster)
1. Download the artifact and unzip it. Check the checksum (`sha256sum -c policehq-<stamp>.dump.age.sha256`), then decrypt: `age -d -i duuje-backup.key -o restore.dump policehq-<stamp>.dump.age`.
2. Create an empty PostgreSQL database (a new Render database is fine) and restore:
   `pg_restore --no-owner --no-privileges --dbname "<new database URL>" restore.dump`
3. Point the web service at the new database (`POSTGRES_*` / `DATABASE_URL` settings) with the SAME `FIELD_ENCRYPTION_KEY` (and `FIELD_HMAC_KEY`), then deploy. Do not run the sample seed against it.
4. Sign in as the super admin, check the dashboard and the audit log, and delete `restore.dump` securely.

## Practise it
Twice a year do a real restore into a throwaway database and sign in. The nightly job proves the dump loads; only a drill proves you know the steps and still have the private key and the field encryption keys.

## Privacy note
The backup contains personnel and payroll data. It is encrypted before it is stored, but GitHub's servers may be outside your jurisdiction: if policy requires data to stay in-country, replace the artifact step with an upload to storage you control (the encrypted file is the only thing that leaves the runner).
