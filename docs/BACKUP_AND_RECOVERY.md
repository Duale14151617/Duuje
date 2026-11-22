# Backup and recovery

## Switching it on
The workflow ships **manual-only** so an unconfigured copy never fails every night. After the setup below works by hand, enable the nightly run by following the comment at the top of `.github/workflows/backup.yml`.

## What happens
`.github/workflows/backup.yml` runs every night (02:30 UTC) and on demand:
1. dumps the production database (`pg_dump`, custom format);
2. **restores it into a scratch database and checks it** (tables, migrations and audit events exist), so a backup that cannot be restored fails the job and GitHub emails you;
3. encrypts it with AES-256 (`gpg`, integrity-protected) using `BACKUP_PASSPHRASE`, deletes the plain copy;
4. keeps the encrypted file as a private workflow artifact for 30 days.

Recovery point: at most 24 hours of data. Recovery time: roughly an hour, most of it spent following the steps below.

## One-time setup
1. In Render, open the database and copy the **External Database URL**. Allow your connections to it (Render's access control list must permit GitHub's runners, or leave it open and rely on the password plus TLS).
2. GitHub repository: Settings, Secrets and variables, Actions: add `BACKUP_DATABASE_URL` and `BACKUP_PASSPHRASE` (20+ random characters).
3. Save in your password manager: the passphrase, `FIELD_ENCRYPTION_KEY` (and any older key), and `FIELD_HMAC_KEY` if set. **A backup without those cannot be read.** Keep one offline copy (printed or on a USB stick) in a different place from your laptop.
4. Run the workflow once by hand (Actions, Encrypted database backup, Run workflow) and confirm it is green.

## Beyond 30 days
Artifacts expire. Once a month, download the newest `database-backup` artifact and keep it somewhere you control (external drive, a second cloud account). It is encrypted, so storage can be untrusted. Also turn on Render's own database backups if your plan has them: two independent copies.

## Restore (disaster)
1. Download the artifact, unzip, decrypt: `gpg --output restore.dump --decrypt duuje-<stamp>.dump.gpg` (enter the passphrase).
2. Create an empty PostgreSQL database (a new Render database is fine) and restore:
   `pg_restore --no-owner --no-privileges --dbname "<new database URL>" restore.dump`
3. Point the web service at the new database (`POSTGRES_*` / `DATABASE_URL` settings) with the SAME `FIELD_ENCRYPTION_KEY` (and `FIELD_HMAC_KEY`), then deploy. Do not run the sample seed against it.
4. Sign in as the super admin, check the dashboard and the audit log, and delete `restore.dump` securely.

## Practise it
Twice a year do a real restore into a throwaway database and sign in. The nightly job proves the dump loads; only a drill proves you know the steps and still have the keys.

## Privacy note
The backup contains personnel and payroll data. It is encrypted before it is stored, but GitHub's servers may be outside your jurisdiction: if policy requires data to stay in-country, replace the artifact step with an upload to storage you control (the encrypted file is the only thing that leaves the runner).
