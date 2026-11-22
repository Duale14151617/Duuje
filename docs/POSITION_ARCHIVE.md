# Retiring old vehicle positions: signed archive, then controlled purge

Position rows are append-only. The database refuses every delete on `vehicle_positions`, except one narrow case that this procedure
creates: a row that a **signed archive in the ledger covers**, that is **older than 30 days**, deleted inside a transaction that names
that archive. Nothing else can delete a position, including a compromised application account.

## What you need (once)
1. Make a signing key: `python manage.py archive_keygen`. Keep the **private** half in a password vault or HSM. Set it as
   `ARCHIVE_SIGNING_KEY` only on the machine that runs the two commands. It must not be in the repository or in database backups.
2. Give the **public** half to whoever must be able to verify archives (an auditor, the ministry). Optionally set it as `ARCHIVE_PUBLIC_KEYS`
   (comma separated; list retired keys too so old archives still verify).
3. `FIELD_ENCRYPTION_KEY` must be set as in production: archives are encrypted with it. Keep every key that was ever used for an archive
   (see `docs/KEY_ROTATION.md`), or old archives become unreadable.

## Each time
1. **Archive** (deletes nothing):
   `python manage.py archive_positions --out-dir /secure/archives --by "Full Name" [--older-than-days 365] [--max-rows 200000]`
   Takes the oldest positions (voided ones too) before the cut-off, up to `--max-rows`. It writes a `.zip`, reads it back and checks it,
   and records the batch in the ledger. It prints the file name, batch id and SHA-256. Only one open batch can exist at a time.
2. **Copy the archive off the server** and check it where the signing machine is not involved:
   `python ops/verify_position_archive.py FILE.zip --public-key <public key>` prints the signed manifest and `VALID`.
   Verifying needs no database and no data key. Reading the rows needs the data key.
3. **Wait** for the cooling-off time (`POSITION_PURGE_COOL_OFF_HOURS`, default 24).
4. **Dry run**: `python manage.py purge_positions --archive FILE.zip --by "Full Name"`. It reports how many rows are unchanged (would be
   deleted), changed since archiving (kept) and already gone.
5. **Purge**: add `--apply --confirm <first 8 characters of the batch id> --confirm-count <rows in the archive>`. The person responsible
   types both, so a pasted command cannot run unseen. Rows go in chunks of 1000, each in its own transaction.
6. To give a batch up instead: `purge_positions --archive FILE.zip --by NAME --abandon`. Nothing is deleted and the next archive can start.

## What protects you
- The purge refuses an archive whose signature or checksum is wrong, that is not in this system's ledger, that was already purged or
  abandoned, or that holds a position newer than 30 days.
- A row **changed after archiving** (for example voided) is **not** deleted. It stays and goes into the next archive with its new content.
- Every archive, purge and abandon is written to the audit log (`vehicle.positions_archive`, `vehicle.positions_purge`,
  `vehicle.positions_archive_abandon`) with who ran it, the row count and the SHA-256. Ledger rows are never deleted.
- Positions inside an archive are encrypted. A lost archive file does not disclose locations without the data key.

## Limits to know
- Archives are only as safe as where you keep them. Keep at least two copies in different places, and test reading one yearly
  (`ARCHIVE_PUBLIC_KEYS` + data key + `archive.read_rows`).
- On SQLite (development and tests) the database trigger does not exist; the commands still enforce every check, but only PostgreSQL
  refuses a rogue delete.
- A retired signing key can still verify old archives if its public half stays in `ARCHIVE_PUBLIC_KEYS`.
- Trip logs, trackers and the audit log are not touched by this procedure.
