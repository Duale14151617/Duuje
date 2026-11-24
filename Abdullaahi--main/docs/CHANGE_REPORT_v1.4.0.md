# Change report: Version 1.4.0

Base: Version 1.3 (same repository; no product module added or removed). Scope: security and reliability hardening,
operations documents and scripts, test evidence. No tactical features; synthetic data only.

## Verification actually performed
| Check | Result |
|---|---|
| `py_compile` on all backend Python (including tests) | passed |
| Static scan: undefined names / unused imports | passed (one intentional import for check registration) |
| Log-redaction function executed against sample secrets (pure Python) | passed |
| Somali/English key parity, empty strings, placeholders, duplicates (Node) | passed (490 keys each) |
| Every static `t("...")` key exists | passed |
| `bash -n` on `ops/*.sh`; CI workflow YAML parses | passed |

## NOT run (no network / no Django, PostgreSQL or npm packages in the authoring environment)
- **All 203 backend tests** (new in 1.4: 64): not executed. This includes the deny-by-default sweep, the
  cross-region canary matrix, the CSRF/CORS/session/MFA/recovery tests, migration safety and query-count tests.
- PostgreSQL-only checks (append-only triggers, parallel stock requests): not executed.
- `makemigrations --check` (the new `accounts/0002`, `logistics/0002`, `personnel/0002`, `workflows/0002` migrations are hand-written; a test now fails loudly if they disagree with the models): not run.
- `check --deploy`, `pip-audit`, `npm audit`, lint, typecheck, vitest, Playwright accessibility/layout tests: not run.
- **Backup, restore test, migration round-trip, monitoring/alert path, incident drill: NOT PERFORMED.** Scripts and procedures are provided; the restore-test log in `docs/RUNBOOK.md` is empty on purpose.
- Accessibility with assistive technology, Android device testing, Somali proofreading, load/performance measurement, independent security review: **not done**.

## Changes and why (details in docs/SECURITY.md)
Throttle bypass via spoofed `X-Forwarded-For`; TOTP replay; absolute session lifetime (sessions lacking a login time are
rejected); one-time password recovery codes; timing oracle on locked accounts; PostgreSQL append-only triggers and
matching application guards for six history/ledger tables; audited audit reads; request-size limit; API security headers;
`bulk` rate limit and parser hardening for CSV import/export; retention job for import batches; log redaction;
`check --deploy` rules; health endpoints; `__Host-` cookies in production; `security_report` command.

## Behaviour changes to be aware of
- Existing sessions have no login timestamp and are signed out once after upgrading.
- TOTP: a code can be used once; users who log in twice within 30 seconds must wait for the next code.
- Password recovery: `users/<id>/issue-reset-code/` and `auth/password/reset/` are new; `reset-password` (admin-chosen temporary password) still exists.
- `/auth/*`, import/export endpoints and health endpoints have rate-limit/permission changes as described; `NUM_PROXIES` is 0 unless `TRUST_PROXY_HEADERS=1`.
- Production cookie names change (`__Host-armyhq-session`, `__Host-armyhq-csrf`).
- New tables/columns: `users.mfa_last_step`, `password_reset_tokens` (non-destructive). Triggers can be removed with `migrate <app> <previous>` (reversible).
- Users with history can no longer be deleted at database level (the new triggers block the foreign-key SET NULL update): disable instead.

## Correction to earlier releases
Since 1.0 the shared test helper (`make_user`) granted MFA to every test user. Several earlier tests that sign in with
a password alone as a non-privileged user would therefore have failed on first run. Fixed here (MFA only for
privileged roles by default). This is a test defect, not an application defect, and it shows the earlier suites were
never executed.

## Test counts (methods written, not run)
accounts: 50, personnel: 26, workflows: 24, logistics: 31, training: 8, core: 64; total 203.


## Files created (34)
- `.github/workflows/ci.yml`
- `backend/.dockerignore`
- `backend/Dockerfile`
- `backend/apps/accounts/migrations/0002_mfa_replay_and_password_reset.py`
- `backend/apps/audit/management/__init__.py`
- `backend/apps/audit/management/commands/__init__.py`
- `backend/apps/audit/management/commands/security_report.py`
- `backend/apps/core/checks.py`
- `backend/apps/core/db_triggers.py`
- `backend/apps/core/tests/__init__.py`
- `backend/apps/core/tests/test_authorization_sweep.py`
- `backend/apps/core/tests/test_hardening.py`
- `backend/apps/core/tests/test_migrations_and_performance.py`
- `backend/apps/core/tests/test_scope_matrix.py`
- `backend/apps/core/views.py`
- `backend/apps/logistics/migrations/0002_append_only_triggers.py`
- `backend/apps/logistics/tests/test_concurrency_pg.py`
- `backend/apps/personnel/management/__init__.py`
- `backend/apps/personnel/management/commands/__init__.py`
- `backend/apps/personnel/management/commands/purge_import_batches.py`
- `backend/apps/personnel/migrations/0002_append_only_triggers.py`
- `backend/apps/workflows/migrations/0002_append_only_triggers.py`
- `backend/requirements-dev.txt`
- `deploy/nginx.conf.example`
- `docs/RUNBOOK.md`
- `docs/SECURITY.md`
- `docs/TEST_PLAN_1.4.md`
- `frontend/e2e/smoke.spec.ts`
- `frontend/eslint.config.js`
- `frontend/playwright.config.ts`
- `frontend/src/pages/Reset.tsx`
- `ops/backup.sh`
- `ops/migration_roundtrip.sh`
- `ops/restore_test.sh`

## Files modified (31)
- `.env.example`
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/accounts/middleware.py`
- `backend/apps/accounts/models.py`
- `backend/apps/accounts/security.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/views.py`
- `backend/apps/audit/views.py`
- `backend/apps/core/apps.py`
- `backend/apps/core/logging.py`
- `backend/apps/core/middleware.py`
- `backend/apps/core/testing.py`
- `backend/apps/logistics/views.py`
- `backend/apps/personnel/models.py`
- `backend/apps/personnel/services.py`
- `backend/apps/personnel/views.py`
- `backend/apps/workflows/models.py`
- `backend/apps/workflows/views.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `docs/DEPLOY_ROLLBACK.md`
- `docs/LIMITATIONS.md`
- `docs/SETUP.md`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/so.ts`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Users.tsx`

## Files removed (0)
- none

## Files unchanged (125)
- `.gitignore`
- `backend/apps/__init__.py`
- `backend/apps/accounts/__init__.py`
- `backend/apps/accounts/apps.py`
- `backend/apps/accounts/management/__init__.py`
- `backend/apps/accounts/management/commands/__init__.py`
- `backend/apps/accounts/management/commands/create_hq_admin.py`
- `backend/apps/accounts/management/commands/seed_demo_data.py`
- `backend/apps/accounts/migrations/0001_initial.py`
- `backend/apps/accounts/migrations/__init__.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/accounts/scope.py`
- `backend/apps/accounts/services.py`
- `backend/apps/accounts/tests/__init__.py`
- `backend/apps/accounts/tests/test_audit_ranks_org.py`
- `backend/apps/accounts/tests/test_auth.py`
- `backend/apps/accounts/tests/test_scope.py`
- `backend/apps/accounts/tests/test_users.py`
- `backend/apps/audit/__init__.py`
- `backend/apps/audit/apps.py`
- `backend/apps/audit/migrations/0001_initial.py`
- `backend/apps/audit/migrations/0002_immutability_trigger.py`
- `backend/apps/audit/migrations/__init__.py`
- `backend/apps/audit/models.py`
- `backend/apps/audit/serializers.py`
- `backend/apps/audit/services.py`
- `backend/apps/core/__init__.py`
- `backend/apps/core/appendonly.py`
- `backend/apps/core/concurrency.py`
- `backend/apps/core/crypto.py`
- `backend/apps/core/errors.py`
- `backend/apps/core/exceptions.py`
- `backend/apps/core/management/__init__.py`
- `backend/apps/core/management/commands/__init__.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
- `backend/apps/core/negotiation.py`
- `backend/apps/core/orgpaths.py`
- `backend/apps/core/pagination.py`
- `backend/apps/core/params.py`
- `backend/apps/dashboard/__init__.py`
- `backend/apps/dashboard/apps.py`
- `backend/apps/dashboard/views.py`
- `backend/apps/logistics/__init__.py`
- `backend/apps/logistics/apps.py`
- `backend/apps/logistics/migrations/0001_initial.py`
- `backend/apps/logistics/migrations/__init__.py`
- `backend/apps/logistics/models.py`
- `backend/apps/logistics/serializers.py`
- `backend/apps/logistics/services.py`
- `backend/apps/logistics/tests/__init__.py`
- `backend/apps/logistics/tests/test_logistics.py`
- `backend/apps/organization/__init__.py`
- `backend/apps/organization/apps.py`
- `backend/apps/organization/migrations/0001_initial.py`
- `backend/apps/organization/migrations/__init__.py`
- `backend/apps/organization/models.py`
- `backend/apps/organization/serializers.py`
- `backend/apps/organization/views.py`
- `backend/apps/personnel/__init__.py`
- `backend/apps/personnel/apps.py`
- `backend/apps/personnel/migrations/0001_initial.py`
- `backend/apps/personnel/migrations/__init__.py`
- `backend/apps/personnel/serializers.py`
- `backend/apps/personnel/tests/__init__.py`
- `backend/apps/personnel/tests/test_personnel.py`
- `backend/apps/ranks/__init__.py`
- `backend/apps/ranks/apps.py`
- `backend/apps/ranks/migrations/0001_initial.py`
- `backend/apps/ranks/migrations/__init__.py`
- `backend/apps/ranks/models.py`
- `backend/apps/ranks/serializers.py`
- `backend/apps/ranks/views.py`
- `backend/apps/training/__init__.py`
- `backend/apps/training/apps.py`
- `backend/apps/training/migrations/0001_initial.py`
- `backend/apps/training/migrations/__init__.py`
- `backend/apps/training/models.py`
- `backend/apps/training/serializers.py`
- `backend/apps/training/services.py`
- `backend/apps/training/tests/__init__.py`
- `backend/apps/training/tests/test_training.py`
- `backend/apps/training/views.py`
- `backend/apps/workflows/__init__.py`
- `backend/apps/workflows/apps.py`
- `backend/apps/workflows/migrations/0001_initial.py`
- `backend/apps/workflows/migrations/__init__.py`
- `backend/apps/workflows/serializers.py`
- `backend/apps/workflows/services.py`
- `backend/apps/workflows/tests/__init__.py`
- `backend/apps/workflows/tests/test_workflows.py`
- `backend/config/__init__.py`
- `backend/config/urls.py`
- `backend/config/wsgi.py`
- `backend/manage.py`
- `backend/requirements.txt`
- `docker-compose.yml`
- `docs/CHANGE_REPORT_v1.0.md`
- `docs/CHANGE_REPORT_v1.1.0.md`
- `docs/CHANGE_REPORT_v1.2.0.md`
- `docs/CHANGE_REPORT_v1.3.0.md`
- `frontend/index.html`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/api/useFetch.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/src/components/hooks.ts`
- `frontend/src/components/ui.tsx`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/i18n/index.tsx`
- `frontend/src/main.tsx`
- `frontend/src/pages/AuditLog.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Enrol.tsx`
- `frontend/src/pages/Logistics.tsx`
- `frontend/src/pages/Notifications.tsx`
- `frontend/src/pages/Organization.tsx`
- `frontend/src/pages/Personnel.tsx`
- `frontend/src/pages/Ranks.tsx`
- `frontend/src/pages/Reports.tsx`
- `frontend/src/pages/Summary.tsx`
- `frontend/src/pages/Training.tsx`
- `frontend/src/styles.css`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
