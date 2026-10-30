# Operations runbook (draft for Version 1.4)

Placeholders in **[brackets]** must be filled in by the institution. Nothing here has been rehearsed by the author.

## 1. People and custody
| Role | Name / contact |
|---|---|
| System owner (accepts risk, approves access) | [ ] |
| Technical operator on call | [ ] |
| Backup key custodians (two, offline) | [ ] / [ ] |
| Incident lead | [ ] |

## 2. Scheduled jobs
```cron
# nightly encrypted backup, then copy off-host (the copy step is yours to add)
15 1 * * *  cd /srv/armyhq && ops/backup.sh
# remove expired CSV previews (personal data) and Django sessions
30 1 * * *  cd /srv/armyhq/backend && python manage.py purge_import_batches && python manage.py clearsessions
# security counters every 5 minutes; exit code 2 means a threshold was exceeded
*/5 * * * * cd /srv/armyhq/backend && python manage.py security_report --minutes 5 || /usr/local/bin/alert "armyhq security thresholds exceeded"
```

## 3. Backup and restore
**Backup** (`ops/backup.sh`): `pg_dump -Fc` encrypted to an `age` public key; checksum file alongside; 30-day local retention.
Keep at least one copy off-host and offline. The private key lives only with the custodians, never on the server.

**Restore test** (`ops/restore_test.sh <archive>`): verifies the checksum, restores into a scratch database
(refuses the live name), counts key tables, checks the append-only triggers exist, checks ledger balances, runs
`showmigrations`/`check` against the copy, then drops the scratch database. Run at least once before any real use,
after every schema change, and quarterly. Ledger-balance check note: demo data seeds quantities without ledger
entries, so run the check on real-shaped data only.

**Recovery of production** (after loss of the database): stop writes (maintenance page) → provision PostgreSQL →
create roles (`docs/DEPLOY_ROLLBACK.md`) → `age -d` + `pg_restore` into an empty database → `migrate` →
`check --deploy` → smoke test → resume. Everything after the backup time is lost. Record RPO/RTO targets: **[RPO: ] [RTO: ]**.

### Restore test log (to be completed by the operator)
| Date | Archive | Restored by | Duration | Checks passed | Notes |
|---|---|---|---|---|---|
| **NOT YET PERFORMED** | | | | | |

## 4. Monitoring and alerting
| Signal | Source | Suggested alert |
|---|---|---|
| Service up / ready | `GET /api/v1/health/live/` and `/ready/` (restrict `/ready/` to the monitor) | not 200 for 2 min |
| Failed sign-ins, lockouts, denied requests, exports, resets | `manage.py security_report` | any threshold breach (defaults 50 / 5 / 100 / 10 per window) |
| Role or account changes | audit actions `role_assignment.create`, `user.disable`, `user.reset_mfa`, `user.issue_reset_code` | notify the system owner of every grant |
| Server errors | 5xx in proxy/app logs (each carries `X-Request-ID`) | >1% of requests for 5 min |
| Throttling | 429 rate | sudden spike (credential stuffing) |
| Backups | newest `armyhq-*.dump.age` age; restore-test age | backup >26 h old; restore test >100 days old |
| Capacity | DB size, disk, connections | 80% |
| Certificates | expiry | 21 days |
| Clock | NTP offset | >5 s (breaks TOTP and audit time) |

## 5. Incident response
Phases: **detect → contain → assess → eradicate/recover → notify → review.** Keep a timestamped log. Correlate with the
`X-Request-ID` / `correlation_id` in audit events and logs.

- **Suspected account compromise:** disable the account (`users/<id>/disable`) and revoke sessions; reset MFA and issue a
  recovery code only after identity is confirmed in person or via a channel the institution trusts; review that
  account's audit trail (`audit-events?actor=<username>`); review role grants it made.
- **Cross-scope exposure suspected (someone saw another region's data):** record the request IDs; revoke the sessions;
  take the affected endpoint out of service at the proxy if needed; preserve audit rows; assess which records were
  returned; notify the system owner immediately; do not "fix" data before evidence is saved.
- **Administrator misuse:** the owner disables the account; audit all `role_assignment.*` and `user.*` events by that actor.
- **Lost or stolen device:** disable the account or revoke sessions at once; reset MFA; re-enrol after identity is verified.
- **Database loss or corruption / ransomware:** isolate, preserve, restore from the last good backup into clean infrastructure (section 3).
- **Leaked secret (key, password, backup key):** rotate `DJANGO_SECRET_KEY` (signs sessions out), re-encrypt MFA secrets
  after rotating `FIELD_ENCRYPTION_KEY` (users must re-enrol MFA unless a re-encryption script is written), rotate DB
  passwords, replace backup keys and re-encrypt retained backups.
Notification duties, contacts and legal obligations: **[to be defined by the institution]**.

## 6. Rollback
- **Code only:** redeploy the previous tag; health check; smoke test.
- **With migrations:** prefer restoring the pre-release backup into a fresh database. Individual reversals are possible
  (`migrate <app> <previous>`; the append-only trigger migrations reverse cleanly) but rehearse them with
  `ops/migration_roundtrip.sh` first. Never reverse on production without a fresh backup.
- **Settings:** every export/doc/debug flag defaults off; rolling back a setting is a restart.

## 7. Release checklist
1. CI green on PostgreSQL (tests, `makemigrations --check`, `check --deploy`, `pip-audit`, `npm audit`, build).
2. Fresh backup taken and restore test less than 100 days old.
3. `ops/migration_roundtrip.sh` run on a copy of production-shaped data.
4. Deploy, `migrate`, `seed_reference_data`, `apply_army_structure --apply` and `retire_police --apply` (dry run first without `--apply`), `check --deploy`.
5. Smoke test: sign in (with MFA), one screen per module, audit events appear, `/ready/` green.
6. Tag the release; record who approved it.
