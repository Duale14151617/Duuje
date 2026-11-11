# Change report: Version 1.3.0

Base: Version 1.2 (same repository; no feature removed). Scope: logistics inventory and training only. No tactical or
operational logistics; no person-by-person equipment directory; synthetic data only.

## Verification actually performed
| Check | Result |
|---|---|
| `py_compile` on all backend Python (including tests) | passed |
| Static scan: undefined names / unused imports | passed |
| Migration vs model field cross-check (every app, script) | passed |
| Somali/English key parity, empty strings, placeholders, duplicates (Node) | passed (476 keys each) |
| Every static `t("...")` key and all dynamic status/action/event/kind keys exist | passed |

## NOT run (no network / no Django or npm packages in the authoring environment)
- Backend tests (138 in total; 38 new logistics/training tests): **not executed**.
- `makemigrations --check` / `migrate` (new `logistics/0001` and `training/0001` are hand-written): **not run**.
- Frontend `npm install`, typecheck, build, vitest; browser and Android checks; accessibility; performance: **not done**.
- Concurrency behaviour under real parallel requests (row locks) is designed for PostgreSQL but **not exercised**; SQLite
  ignores `select_for_update`, so the automated tests check balances and guards, not true parallelism.

## Self-review fixes made during this release
- Audit migration 0001 listed a model manager, which would make `makemigrations --check` report a change. Removed.
- `versioned_update` needs an `updated_at` column; `Reconciliation` lacked one. Added (model + migration).
- Training enrolment resolved the person through a model-wide field, which would have let callers distinguish
  "exists but out of scope" from "does not exist". It now resolves through the caller's own scope only.
- `ScopedPermission` object-level checks now accept any-of permission lists (needed for restricted/normal viewers).

## Correction to earlier reports
The test counts quoted in the 1.0, 1.1 and 1.2 change reports were overstated. Actual counts: 49 (1.0), 76 (1.1),
100 (1.2), 138 (1.3). The tests themselves are as described; only the totals were wrong.

## Behaviour changes to be aware of
- New permissions and roles (`restricted_custodian`, `logistics_reviewer`); `hq_admin` gets only `logistics.configure`
  and `training.configure` (no inventory or training-record access). Re-run `seed_reference_data` after upgrading.
- New tables: inventory_categories, stock_lines, stock_transactions, assets, asset_events, reconciliations,
  reconciliation_lines, training_courses, training_records (non-destructive). Rollback: `migrate logistics zero` and
  `migrate training zero`, or restore the pre-release backup.
- New shared helpers: `core/appendonly.py`, `core/orgpaths.py`.

## Tests added (to be run)
Categories (draft until reviewed, review rules, creator cannot approve, restricted hidden, HQ-only configuration);
stock (ledger exactness, negative stock and invalid transactions, stale-balance guard, append-only ledger, transfers
conserve stock and pair entries, cannot push into unmanaged units, line rules, cross-scope blocking, view-only roles,
reorder filter); assets and restricted equipment (separate permission for visibility and action, audited denial,
no link to personnel enforced by introspection, identifier rules and duplicates, full lifecycle, issue/transfer target
checks, versioning, custodianship rules, filters); reconciliation (variances and missing/found handling, current-balance
rule, permissions, validation, restricted separation); summaries (scope and restricted rows); training (HQ-only
catalogue, enrolment rules, scope-blind person lookup, status transitions and completion dates, editing and
versioning, scope and role boundaries, minimal roster and no personnel access, summaries).


## Files created (25)
- `backend/apps/core/appendonly.py`
- `backend/apps/core/orgpaths.py`
- `backend/apps/logistics/__init__.py`
- `backend/apps/logistics/apps.py`
- `backend/apps/logistics/migrations/0001_initial.py`
- `backend/apps/logistics/migrations/__init__.py`
- `backend/apps/logistics/models.py`
- `backend/apps/logistics/serializers.py`
- `backend/apps/logistics/services.py`
- `backend/apps/logistics/tests/__init__.py`
- `backend/apps/logistics/tests/test_logistics.py`
- `backend/apps/logistics/views.py`
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
- `frontend/src/components/hooks.ts`
- `frontend/src/pages/Logistics.tsx`
- `frontend/src/pages/Training.tsx`

## Files modified (20)
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/accounts/management/commands/seed_demo_data.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/audit/migrations/0001_initial.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
- `backend/apps/dashboard/views.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `docs/LIMITATIONS.md`
- `docs/SETUP.md`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api/types.ts`
- `frontend/src/components/Layout.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/so.ts`
- `frontend/src/pages/Dashboard.tsx`

## Files removed (0)
- none

## Files unchanged (110)
- `.env.example`
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
- `backend/apps/accounts/views.py`
- `backend/apps/audit/__init__.py`
- `backend/apps/audit/apps.py`
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
- `backend/apps/core/negotiation.py`
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
- `backend/apps/personnel/views.py`
- `backend/apps/ranks/__init__.py`
- `backend/apps/ranks/apps.py`
- `backend/apps/ranks/migrations/0001_initial.py`
- `backend/apps/ranks/migrations/__init__.py`
- `backend/apps/ranks/models.py`
- `backend/apps/ranks/serializers.py`
- `backend/apps/ranks/views.py`
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
- `backend/config/__init__.py`
- `backend/config/urls.py`
- `backend/config/wsgi.py`
- `backend/manage.py`
- `backend/requirements.txt`
- `docker-compose.yml`
- `docs/CHANGE_REPORT_v1.0.md`
- `docs/CHANGE_REPORT_v1.1.0.md`
- `docs/CHANGE_REPORT_v1.2.0.md`
- `docs/DEPLOY_ROLLBACK.md`
- `frontend/index.html`
- `frontend/src/api/client.ts`
- `frontend/src/api/useFetch.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/i18n/i18n.test.ts`
- `frontend/src/i18n/index.tsx`
- `frontend/src/main.tsx`
- `frontend/src/pages/AuditLog.tsx`
- `frontend/src/pages/Enrol.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Notifications.tsx`
- `frontend/src/pages/Organization.tsx`
- `frontend/src/pages/Personnel.tsx`
- `frontend/src/pages/Ranks.tsx`
- `frontend/src/pages/Reports.tsx`
- `frontend/src/pages/Summary.tsx`
- `frontend/src/pages/Users.tsx`
- `frontend/src/styles.css`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
