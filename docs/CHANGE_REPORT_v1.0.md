# Change report: Version 1.0 (Foundation)

Base: none (first release, new repository). Created: every file listed below. Modified: none. Unchanged: none.
Personnel management beyond schema was intentionally NOT built (spec: later version). No tactical features.

## Verification actually performed
| Check | Result |
|---|---|
| `py_compile` on all backend Python | passed |
| Static scan: undefined names / unused imports (custom AST script) | passed after cleanup |
| Somali/English key parity, empty strings, placeholders (run with Node) | passed (169 keys each) |
| Every static `t("...")` key used in TSX exists in the dictionary | passed |

## NOT run (authoring environment had no network and no Django/npm packages)
- Backend test suite (about 60 tests in `backend/apps/accounts/tests/`): **not executed**.
- `makemigrations --check` / `migrate`: **not run**. Migrations are hand-written; they may need regeneration.
- PostgreSQL audit trigger and DB constraints: **not exercised**.
- Frontend `npm install`, `tsc` typecheck, `vite build`, `vitest`: **not run**.
- OpenAPI generation, browser and Android manual testing, accessibility testing, performance testing: **not done**.
Expect small defects on first run; fix them before building 1.1 on top.

## Tests written (to be run)
Auth (login, lockout, CSRF, MFA enrolment/OTP, forced password change, session invalidation on disable/role revoke/
revoke-sessions/logout, no-role user), scope (cross-region, branch-limited, direct ID 404, filter widening, expired
assignment, dashboard blocks), users (admin-only, creation, weak password, assignment rules, last-admin guard,
concurrency, pagination, no secret fields), audit (append-only, read permissions, correlation IDs), ranks (seed is
draft/complete/idempotent, approval workflow, voiding, concurrency, permissions, duplicates), organization rules.

## Files (all created in this release)
- `.env.example`
- `.gitignore`
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/__init__.py`
- `backend/apps/accounts/__init__.py`
- `backend/apps/accounts/apps.py`
- `backend/apps/accounts/management/__init__.py`
- `backend/apps/accounts/management/commands/__init__.py`
- `backend/apps/accounts/management/commands/create_hq_admin.py`
- `backend/apps/accounts/management/commands/seed_demo_data.py`
- `backend/apps/accounts/middleware.py`
- `backend/apps/accounts/migrations/0001_initial.py`
- `backend/apps/accounts/migrations/__init__.py`
- `backend/apps/accounts/models.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/accounts/scope.py`
- `backend/apps/accounts/security.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/services.py`
- `backend/apps/accounts/tests/__init__.py`
- `backend/apps/accounts/tests/test_audit_ranks_org.py`
- `backend/apps/accounts/tests/test_auth.py`
- `backend/apps/accounts/tests/test_scope.py`
- `backend/apps/accounts/tests/test_users.py`
- `backend/apps/accounts/views.py`
- `backend/apps/audit/__init__.py`
- `backend/apps/audit/apps.py`
- `backend/apps/audit/migrations/0001_initial.py`
- `backend/apps/audit/migrations/0002_immutability_trigger.py`
- `backend/apps/audit/migrations/__init__.py`
- `backend/apps/audit/models.py`
- `backend/apps/audit/serializers.py`
- `backend/apps/audit/services.py`
- `backend/apps/audit/views.py`
- `backend/apps/core/__init__.py`
- `backend/apps/core/apps.py`
- `backend/apps/core/concurrency.py`
- `backend/apps/core/crypto.py`
- `backend/apps/core/exceptions.py`
- `backend/apps/core/logging.py`
- `backend/apps/core/management/__init__.py`
- `backend/apps/core/management/commands/__init__.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
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
- `backend/apps/organization/views.py`
- `backend/apps/ranks/__init__.py`
- `backend/apps/ranks/apps.py`
- `backend/apps/ranks/migrations/0001_initial.py`
- `backend/apps/ranks/migrations/__init__.py`
- `backend/apps/ranks/models.py`
- `backend/apps/ranks/serializers.py`
- `backend/apps/ranks/views.py`
- `backend/config/__init__.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `backend/config/urls.py`
- `backend/config/wsgi.py`
- `backend/manage.py`
- `backend/requirements.txt`
- `docker-compose.yml`
- `docs/DEPLOY_ROLLBACK.md`
- `docs/LIMITATIONS.md`
- `docs/SETUP.md`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/api/useFetch.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/i18n/index.tsx`
- `frontend/src/i18n/so.ts`
- `frontend/src/main.tsx`
- `frontend/src/pages/AuditLog.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Enrol.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Organization.tsx`
- `frontend/src/pages/Ranks.tsx`
- `frontend/src/pages/Users.tsx`
- `frontend/src/styles.css`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`

See `docs/LIMITATIONS.md` for known limitations, security concerns and prerequisites for 1.1.
