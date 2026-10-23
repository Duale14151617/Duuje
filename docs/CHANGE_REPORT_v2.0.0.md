# Change report — Version 2.0.0 (from 1.4.0)

## Summary
Additive release: scoped analytics, read-only integration API (off by default), scoped unit tree, docs and tests. See `IMPACT_ASSESSMENT_v2.0.md` for what was and was not built and why.

Post-release hardening in this package: integration keys cannot use `?unit=` unless `INTEGRATION_ALLOW_UNIT_FILTER=1`; `integration_report` flags keys whose creator was disabled or lost the granted access (3 added tests).

Governed structure changes (added in this package): proposal/approval workflow for the configurable subordinate levels (`docs/STRUCTURE_APPROVAL.md`), new model/migration `organization.0004`, role `structure_approver`, permissions `org.structure_propose`/`org.structure_approve`, page *Structure changes*, 25 new tests. **Behaviour change:** direct edits of unit types are refused unless `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0` (the 3 existing 1.4 tests of the direct editor were adapted to run with it off). Also fixed a bug in my own compatibility test (it did not expect `hq_admin` to gain the integration permissions).

## Verification status (honest)
**Done in the authoring environment (no network, no Django/PostgreSQL/npm packages):**
- `compileall` of the whole backend (all files compile).
- English/Somali key parity (677 keys each), placeholder parity, every static and dynamic `t()` key used by new pages exists.
- Pure logic executed outside Django: small-cell protection function and the integration key format (20,000 random keys parsed).
- Loose TypeScript syntax check of new pages with stubbed React types (no syntax errors; a real typecheck was **not** possible).
- Frozen 1.4 baselines for the compatibility tests were extracted mechanically from the 1.4.0 sources.

**NOT run (must be run before use):** `python manage.py makemigrations --check` (the integrations migrations are hand-written), `python manage.py test apps` (all new tests unexecuted; existing suites untested against 2.0), migrations on PostgreSQL, trigger behaviour, `npm run typecheck/lint/test/build`, e2e/accessibility, load/performance, Android/desktop layout checks, independent security review. The 1.4.0 base is described as working by the project owner; that was not re-verified.

## Created (38, including this report)
- `backend/apps/analytics/__init__.py`
- `backend/apps/analytics/apps.py`
- `backend/apps/analytics/services.py`
- `backend/apps/analytics/tests/__init__.py`
- `backend/apps/analytics/tests/test_analytics.py`
- `backend/apps/analytics/views.py`
- `backend/apps/core/tests/test_v2_compatibility.py`
- `backend/apps/integrations/__init__.py`
- `backend/apps/integrations/apps.py`
- `backend/apps/integrations/authentication.py`
- `backend/apps/integrations/management/__init__.py`
- `backend/apps/integrations/management/commands/__init__.py`
- `backend/apps/integrations/management/commands/integration_report.py`
- `backend/apps/integrations/migrations/0001_initial.py`
- `backend/apps/integrations/migrations/0002_append_only_triggers.py`
- `backend/apps/integrations/migrations/__init__.py`
- `backend/apps/integrations/models.py`
- `backend/apps/integrations/serializers.py`
- `backend/apps/integrations/services.py`
- `backend/apps/integrations/tests/__init__.py`
- `backend/apps/integrations/tests/test_integrations.py`
- `backend/apps/integrations/views.py`
- `backend/apps/organization/migrations/0004_structure_change.py`
- `backend/apps/organization/structure_changes.py`
- `backend/apps/organization/tests/test_structure_changes.py`
- `backend/apps/organization/tests/test_tree.py`
- `docs/CHANGE_REPORT_v2.0.0.md`
- `docs/COMPATIBILITY_v2.0.md`
- `docs/IMPACT_ASSESSMENT_v2.0.md`
- `docs/INTEGRATIONS.md`
- `docs/MIGRATION_PLAN_v2.0.md`
- `docs/OFFLINE_DECISION.md`
- `docs/SECURITY_REVIEW_v2.0.md`
- `docs/STRUCTURE_APPROVAL.md`
- `frontend/src/pages/Analytics.tsx`
- `frontend/src/pages/Integrations.tsx`
- `frontend/src/pages/OrgTree.tsx`
- `frontend/src/pages/StructureChanges.tsx`

## Modified (23)
- `.env.example`
- `CHANGELOG.md`
- `README.md`
- `VERSION`
- `backend/apps/accounts/views.py`
- `backend/apps/core/management/commands/seed_reference_data.py`
- `backend/apps/organization/models.py`
- `backend/apps/organization/serializers.py`
- `backend/apps/organization/tests/test_structure.py`
- `backend/apps/organization/views.py`
- `backend/config/api_v1.py`
- `backend/config/settings.py`
- `docs/DEPLOY_ROLLBACK.md`
- `docs/LIMITATIONS.md`
- `docs/SECURITY.md`
- `docs/SETUP.md`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api/types.ts`
- `frontend/src/components/Layout.tsx`
- `frontend/src/i18n/en.ts`
- `frontend/src/i18n/so.ts`
- `frontend/src/styles.css`

## Removed (0)
- none

## Unchanged (188)
All other files, including every 1.x migration, model, service and test, are byte-identical to 1.4.0 (list omitted for length; reproducible by diff against the 1.4.0 package).

## Known limitations and next prerequisites
See `LIMITATIONS.md` (2.0 notes) and `SECURITY_REVIEW_v2.0.md`. Before any real use: run the test suite and `makemigrations --check` on PostgreSQL, review the Somali text, obtain institutional approval for each integration, decide call-log retention and the small-cell threshold, and commission an independent security review.
