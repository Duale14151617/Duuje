# Change report: Version 1.1.0

Base: Version 1.0 (same repository; no feature removed). Scope: personnel management only; no tactical features;
synthetic data only.

## Verification actually performed
| Check | Result |
|---|---|
| `py_compile` on all backend Python | passed |
| Static scan: undefined names / unused imports | passed after cleanup |
| Somali/English key parity, empty strings, placeholders, duplicate keys (Node) | passed (239 keys each) |
| Every static `t("...")` key and every dynamic `pstatus.*` / `hist.*` key exists | passed |

## NOT run (no network / no Django or npm packages in the authoring environment)
- Backend tests (about 95 now, including ~35 new personnel tests): **not executed**.
- `makemigrations --check` / `migrate` (new migration `personnel/0001_initial` is hand-written): **not run**.
- Frontend `npm install`, typecheck, build, vitest; manual browser and Android checks; performance checks: **not done**.

## Bug found and fixed while reviewing (affects 1.0 behaviour)
Hand-raised validation errors used `{"message","code"}` dicts that DRF re-wraps, so clients would have received nested
objects instead of codes (password change, MFA, version-required, language, audit date filter). Replaced everywhere with
`core.errors.field_error`; a regression test was added. Malformed UUID filter values now return 400 instead of 500.

## Behaviour changes to be aware of
- `hq_admin` no longer receives every permission: personnel permissions are excluded on purpose.
- `/auth/me/` now returns `features.personnel_export`.
- New settings/env: `PERSONNEL_EXPORT_ENABLED` (default off). New tables: `personnel`, `personnel_history`,
  `personnel_import_batches` (non-destructive migration). Rollback: `migrate personnel zero` or restore the pre-release backup.
- Re-run `python manage.py seed_reference_data` after upgrading to sync the new permissions and role grants.

## Tests added (to be run)
Cross-scope list/detail/edit/history/transfer, search and filter widening, HQ-admin default denial, read-only limits,
pagination, malformed ids; create rules (scope, unit level, rank/branch mismatch, unapproved rank), service-number and
possible-duplicate handling, phone/number validation; concurrency (edit and workflow, nothing written on conflict);
effective-dated history, future-date and cross-branch rejection; CSV import (preview/commit, out-of-scope rows, atomic
failure, private and expiring batches, unsafe files, permission); export (off by default, scoped, audited, formula-safe,
separate permission).


## Files created (13)
- `backend/apps/core/errors.py`
- `backend/apps/core/params.py`
- `backend/apps/personnel/__init__.py`
- `backend/apps/personnel/apps.py`
- `backend/apps/personnel/migrations/0001_initial.py`
- `backend/apps/personnel/migrations/__init__.py`
- `backend/apps/personnel/models.py`
- `backend/apps/personnel/serializers.py`
- `backend/apps/personnel/services.py`
- `backend/apps/personnel/tests/__init__.py`
- `backend/apps/personnel/tests/test_personnel.py`
- `backend/apps/personnel/views.py`
- `frontend/src/pages/Personnel.tsx`

## Files modified (25)
- `.env.example`
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/accounts/management/commands/seed_demo_data.py`
- `backend/apps/accounts/scope.py`
- `backend/apps/accounts/tests/test_auth.py`
- `backend/apps/accounts/views.py`
- `backend/apps/audit/views.py`
- `backend/apps/core/concurrency.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
- `backend/apps/organization/views.py`
- `backend/apps/ranks/views.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `docs/LIMITATIONS.md`
- `docs/SETUP.md`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/components/Layout.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/so.ts`
- `frontend/src/styles.css`

## Files removed (0)
- none

## Files unchanged (76)
- `.gitignore`
- `backend/apps/__init__.py`
- `backend/apps/accounts/__init__.py`
- `backend/apps/accounts/apps.py`
- `backend/apps/accounts/management/__init__.py`
- `backend/apps/accounts/management/commands/__init__.py`
- `backend/apps/accounts/management/commands/create_hq_admin.py`
- `backend/apps/accounts/middleware.py`
- `backend/apps/accounts/migrations/0001_initial.py`
- `backend/apps/accounts/migrations/__init__.py`
- `backend/apps/accounts/models.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/accounts/security.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/services.py`
- `backend/apps/accounts/tests/__init__.py`
- `backend/apps/accounts/tests/test_audit_ranks_org.py`
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
- `backend/apps/core/apps.py`
- `backend/apps/core/crypto.py`
- `backend/apps/core/exceptions.py`
- `backend/apps/core/logging.py`
- `backend/apps/core/management/__init__.py`
- `backend/apps/core/management/commands/__init__.py`
- `backend/apps/core/middleware.py`
- `backend/apps/core/pagination.py`
- `backend/apps/core/testing.py`
- `backend/apps/dashboard/__init__.py`
- `backend/apps/dashboard/apps.py`
- `backend/apps/dashboard/views.py`
- `backend/apps/organization/__init__.py`
- `backend/apps/organization/apps.py`
- `backend/apps/organization/migrations/0001_initial.py`
- `backend/apps/organization/migrations/__init__.py`
- `backend/apps/organization/models.py`
- `backend/apps/organization/serializers.py`
- `backend/apps/ranks/__init__.py`
- `backend/apps/ranks/apps.py`
- `backend/apps/ranks/migrations/0001_initial.py`
- `backend/apps/ranks/migrations/__init__.py`
- `backend/apps/ranks/models.py`
- `backend/apps/ranks/serializers.py`
- `backend/config/__init__.py`
- `backend/config/urls.py`
- `backend/config/wsgi.py`
- `backend/manage.py`
- `backend/requirements.txt`
- `docker-compose.yml`
- `docs/CHANGE_REPORT_v1.0.md`
- `docs/DEPLOY_ROLLBACK.md`
- `frontend/index.html`
- `frontend/src/api/useFetch.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/i18n/index.tsx`
- `frontend/src/main.tsx`
- `frontend/src/pages/AuditLog.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Enrol.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Organization.tsx`
- `frontend/src/pages/Ranks.tsx`
- `frontend/src/pages/Users.tsx`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
