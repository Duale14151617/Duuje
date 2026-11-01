# Deployment, migration and rollback (outline for 1.0)

Real deployment needs written institutional approval (ownership, hosting, retention, access, incident response).
Do not load real personnel data into this version.

## Database roles (least privilege)
```sql
CREATE ROLE armyhq_owner LOGIN PASSWORD '...';   -- runs migrations only
CREATE ROLE armyhq_app   LOGIN PASSWORD '...';   -- runtime role
CREATE DATABASE armyhq OWNER armyhq_owner;
\c armyhq
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO armyhq_app;
ALTER DEFAULT PRIVILEGES FOR ROLE armyhq_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO armyhq_app;
ALTER DEFAULT PRIVILEGES FOR ROLE armyhq_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO armyhq_app;
-- After migrating, make the audit table insert/select-only for the runtime role:
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM armyhq_app;
```
Run `migrate` with `POSTGRES_USER=armyhq_owner`; run the app as `armyhq_app`.

## Release steps
1. Back up the database (`pg_dump -Fc`), store encrypted off-host. Record the current git tag.
2. Deploy code; set environment (see `.env.example`). `DJANGO_DEBUG` must be 0.
3. `python manage.py migrate` (as owner), `createcachetable`, `seed_reference_data`, `apply_army_structure --apply`, `check --deploy`.
4. `cd frontend && npm ci && npm run build`; serve `dist/` and proxy `/api/` to gunicorn from the **same origin**
   over HTTPS (cookies are Secure/HttpOnly/SameSite=Lax; CSRF relies on same-origin).
5. Smoke test: sign in, open each screen, confirm audit events appear.

## Rollback
- Code only (no new migration): redeploy previous tag.
- With migrations: restore the pre-release `pg_dump` into a fresh database and point the app at it, or run
  `python manage.py migrate <app> <previous_migration>` for reversible steps (audit trigger migration is reversible).
  Anything written after the backup is lost on restore: stop writes first.
- Backup, restore test, monitoring and incident procedures: see `docs/RUNBOOK.md` (scripts in `ops/`). A restore test is required before any real use.

## Added in 1.4
- Production checks: `python manage.py check --deploy --fail-level ERROR` (run in CI and at every release).
- Revoke destructive rights from the runtime role: `REVOKE UPDATE, DELETE, TRUNCATE ON audit_events, stock_transactions, asset_events, personnel_history, approval_actions, submission_revisions FROM armyhq_app;` (the triggers already refuse UPDATE/DELETE; this also covers TRUNCATE).
- Reverse proxy template: `deploy/nginx.conf.example`. Container image: `backend/Dockerfile` (non-root, health check).
- Set `TRUST_PROXY_HEADERS=1` and `NUM_PROXIES=<number of trusted proxies>` only when a proxy overwrites `X-Forwarded-For`; otherwise leave both unset.

## Upgrading to 1.4.0 with the ranks and structure addendum (merged from 1.3.1)
1. **Back up the database first** (the rank migration deletes unused provisional ranks and is not reversible).
2. Deploy the code, then `python manage.py migrate` (runs `organization.0002/0003`, `ranks.0002/0003`).
3. `python manage.py seed_reference_data` (idempotent; does not overwrite administrator edits).
4. `python manage.py report_rank_remap` to see how many people still hold a retired provisional rank, then have an authorised
   user re-rank them (change-rank action). Nothing is re-ranked automatically.
5. Open **Structure** and review the findings; adjust reference figures, exceptions and designation rules as needed.

Rollback: restore the pre-upgrade backup and redeploy the previous release. `organization.0002` can be unapplied
(`migrate organization 0001`), but `ranks.0003` is data-destructive by design and has no reverse.

## Upgrading to 2.0.0
See `docs/MIGRATION_PLAN_v2.0.md` (steps, enabling integrations, four rollback paths).

