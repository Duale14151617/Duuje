# Merge report: Puntland Army rank catalogue and organizational hierarchy (from 1.3.1 into 1.4.0)

Base: 1.4.0 (kept in full). Reference: 1.3.1. Only features present in 1.3.1 and missing from 1.4.0 were merged.
`VERSION` stays 1.4.0.

## Merged
**Rank catalogue:** `ranks/catalogue.py` (16 official ranks, idempotent apply), migrations `ranks/0002` (category
`unspecified`) and `ranks/0003` (data: official ranks added, provisional ones retired/removed without orphaning people),
`report_rank_remap` command, `Rank.Category.UNSPECIFIED`, seeding via `seed_reference_data`.
**Organizational hierarchy:** models `UnitType`, `SpecialistDesignation`, `DesignationRule` and new unit fields
(`unit_type`, `designations`, strength exception); migrations `organization/0002` (schema) and `0003` (data: template +
Taliska Guud tagging); `reference.py`, `structure.py`; API `organization/unit-types|designations|designation-rules|structure`
(all `org.view` read, headquarters `org.manage` write, audited); unit serializer/view validation and audit events; `unit_type`
in the unit brief.
**Frontend:** `Structure` page + nav entry, `UnitPicker`, `useUnitTypes`, Organization page (type, designations, exception,
search, paging), Personnel page (picker, type shown), Ranks page (`unspecified` category), types, 56 EN + 56 SO strings.
**Tests/seed adapted to official ranks:** `organization/tests/test_structure.py` (new), and rank codes `E-n` -> `PA-nn` in the
accounts, personnel, training, scope-matrix and migration/performance tests and in `seed_demo_data`.
**Docs:** README, LIMITATIONS, DEPLOY_ROLLBACK (upgrade steps), CHANGELOG, `CHANGE_REPORT_v1.3.1.md`.

## Adaptations to 1.4
- New viewsets follow 1.4 rules: `ScopedPermission` map covers every action, no PUT/DELETE (authorization sweep).
- Migrations use reversible `RunPython` (noop reverse), as the 1.4 migration-safety test requires; they depend only on
  existing 1.4 migrations. 1.4 files (security, triggers, health, password reset, MFA replay) were not touched.
- One adjacent fix included because the merged detail routes and tests need it: `core/exceptions.py` converts Django
  `Http404`/`PermissionDenied` so an unknown or out-of-scope id returns 404/403 instead of a 500.

## Not merged / left as is
- `Logistics.tsx` type annotation fix noted in 1.3.1 changelog (unrelated to this scope; not applied).

## Verification
Done: `compileall` on backend; EN/SO key parity (546 each); every static `t()` key exists; file-level diff against original 1.4.
NOT run (no Django/PostgreSQL/npm here): backend tests, `makemigrations --check`, migrations, typecheck, build, e2e.
Run `python manage.py test`, `makemigrations --check`, `npm run build` before use.
