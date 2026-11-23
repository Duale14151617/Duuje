# Change report: Version 1.2.0

Base: Version 1.1 (same repository; no feature removed). Scope: requests, reports, approvals, summaries, notifications.
No tactical features; synthetic data only.

## Verification actually performed
| Check | Result |
|---|---|
| `py_compile` on all backend Python (including tests) | passed |
| Static scan: undefined names / unused imports | passed |
| Migration vs model field cross-check (all apps, script) | passed (every model field appears in its migration) |
| Somali/English key parity, empty strings, placeholders, duplicates (Node) | passed (329 keys each) |
| Every static `t("...")` key and all dynamic status/action/figure/notification keys exist | passed |

## NOT run (no network / no Django or npm packages in the authoring environment)
- Backend tests (about 125 in total; about 30 new workflow tests): **not executed**.
- `makemigrations --check` / `migrate` (new `workflows/0001_initial` is hand-written): **not run**.
- Frontend `npm install`, typecheck, build, vitest; browser and Android checks; performance and accessibility testing: **not done**.
Two earlier review passes caught real bugs by reading the code (error-code shape in 1.1; stale `from_status` in this
release), so expect a few more on first execution. Run the suite and fix before building 1.3.

## Behaviour changes to be aware of
- Seeded roles gain report permissions (reporting officers/unit admins submit; regional chiefs and branch admins review;
  HQ reporting users, regional chiefs and branch admins see summaries). `hq_admin` still gets no report or personnel
  content access, only `reports.configure`.
- `ScopedPermission` rules can now name several permission codes (any-of).
- `/auth/me/` returns `features.report_export`. New setting `REPORT_EXPORT_ENABLED` (default off).
- New tables: `report_types`, `submissions`, `submission_revisions`, `approval_actions`, `notifications`
  (non-destructive). Rollback: `migrate workflows zero` or restore the pre-release backup.
- Re-run `python manage.py seed_reference_data` after upgrading.
- The CSV-export negotiation helper moved to `apps/core/negotiation.py` (used by personnel and reports).

## Tests added (to be run)
Lifecycle (happy path with history, notifications and audit; invalid transitions; return/resubmit revisions;
amendment keeps prior approved totals; stale-version races change nothing); separation of duties (blocked and audited;
policy-off allowed and flagged); forgery resistance (status, submitter, reviewer, version, org unit, type); ownership;
role separation; cross-region access on list/detail/transition/create/filter; filters and malformed ids; validation
(figures, periods, completeness); summary totals by region and consolidated excluding drafts/submitted, scope limits,
date/type/unit filters; export off by default, scoped, audited; notification privacy and re-authorization after
scope loss; report-type configuration, in-use protection and concurrency.


## Files created (14)
- `backend/apps/core/negotiation.py`
- `backend/apps/workflows/__init__.py`
- `backend/apps/workflows/apps.py`
- `backend/apps/workflows/migrations/0001_initial.py`
- `backend/apps/workflows/migrations/__init__.py`
- `backend/apps/workflows/models.py`
- `backend/apps/workflows/serializers.py`
- `backend/apps/workflows/services.py`
- `backend/apps/workflows/tests/__init__.py`
- `backend/apps/workflows/tests/test_workflows.py`
- `backend/apps/workflows/views.py`
- `frontend/src/pages/Notifications.tsx`
- `frontend/src/pages/Reports.tsx`
- `frontend/src/pages/Summary.tsx`

## Files modified (22)
- `.env.example`
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/accounts/management/commands/seed_demo_data.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/accounts/views.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
- `backend/apps/dashboard/views.py`
- `backend/apps/personnel/views.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `docs/LIMITATIONS.md`
- `docs/SETUP.md`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api/types.ts`
- `frontend/src/components/Layout.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/so.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/styles.css`

## Files removed (0)
- none

## Files unchanged (93)
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
- `backend/apps/accounts/scope.py`
- `backend/apps/accounts/security.py`
- `backend/apps/accounts/serializers.py`
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
- `backend/apps/audit/views.py`
- `backend/apps/core/__init__.py`
- `backend/apps/core/apps.py`
- `backend/apps/core/concurrency.py`
- `backend/apps/core/crypto.py`
- `backend/apps/core/errors.py`
- `backend/apps/core/exceptions.py`
- `backend/apps/core/logging.py`
- `backend/apps/core/management/__init__.py`
- `backend/apps/core/management/commands/__init__.py`
- `backend/apps/core/middleware.py`
- `backend/apps/core/pagination.py`
- `backend/apps/core/params.py`
- `backend/apps/core/testing.py`
- `backend/apps/dashboard/__init__.py`
- `backend/apps/dashboard/apps.py`
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
- `backend/apps/personnel/models.py`
- `backend/apps/personnel/serializers.py`
- `backend/apps/personnel/services.py`
- `backend/apps/personnel/tests/__init__.py`
- `backend/apps/personnel/tests/test_personnel.py`
- `backend/apps/ranks/__init__.py`
- `backend/apps/ranks/apps.py`
- `backend/apps/ranks/migrations/0001_initial.py`
- `backend/apps/ranks/migrations/__init__.py`
- `backend/apps/ranks/models.py`
- `backend/apps/ranks/serializers.py`
- `backend/apps/ranks/views.py`
- `backend/config/__init__.py`
- `backend/config/urls.py`
- `backend/config/wsgi.py`
- `backend/manage.py`
- `backend/requirements.txt`
- `docker-compose.yml`
- `docs/CHANGE_REPORT_v1.0.md`
- `docs/CHANGE_REPORT_v1.1.0.md`
- `docs/DEPLOY_ROLLBACK.md`
- `frontend/index.html`
- `frontend/src/api/client.ts`
- `frontend/src/api/useFetch.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/i18n/index.tsx`
- `frontend/src/main.tsx`
- `frontend/src/pages/AuditLog.tsx`
- `frontend/src/pages/Enrol.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Organization.tsx`
- `frontend/src/pages/Personnel.tsx`
- `frontend/src/pages/Ranks.tsx`
- `frontend/src/pages/Users.tsx`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
