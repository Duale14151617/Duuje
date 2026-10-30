# Change report — Version 1.3.1 (Puntland Army ranks and organizational structure addendum)

Built on the uploaded `armyhq-v1_3_0.zip`. Only the addendum was implemented; no module was rebuilt or redesigned.
Two small fixes outside the addendum were unavoidable and are listed explicitly under "Fixes outside the addendum".

## What was added
1. **Official Army ranks.** The 16 ranks, in the supplied order and spelling, are stored in the `ranks` table (managed
   through the existing Ranks page/API with its approval workflow and audit). The provisional US-style list is retired.
2. **Regional commands.** Bari, Karkaar, Nugaal and Mudug already existed. Each region's Army branch command is now typed
   **Taliska Guud**.
3. **Hierarchy and reference strengths.** Unit types Taliska Guud, Qayb (6,000–7,000), Gaas (3,500; two per Qayb),
   Guuto (900–1,001), Urur (320–330), Horin (99), Koox (33), Unug (9) are database rows. Figures are reference only: no
   constraint, nothing creates personnel. Units can carry an **approved strength exception** (range + required reason),
   stamped with who recorded it and when.
4. **Specialist designations.** Sahan (reconnaissance) and Sanco (miino baar / bomb squad) are a separate catalogue, not
   ranks, assignable to units. Expected relationships are data rules: Guuto→Horin Sahan, Gaas→Urur Sahan, Gaas→Urur Sanco.
5. **Structure page** (navigation entry "Structure"): template findings, reference vs actual strength per unit (actual
   only where the viewer has personnel.view), and management of unit types, designations and rules by authorised users.
6. **Integration:** Organization page shows type and designations and edits them; Personnel shows the unit type and uses a
   searchable unit picker (a plain dropdown could only reach the first 100 of thousands of units).
7. **Access control and audit:** catalogue changes need headquarters `org.manage`; unit changes need `org.manage` in scope;
   reads need `org.view`. New audit events: `unit_type.*`, `specialist_designation.*`, `designation_rule.*`,
   `org_unit.type_change`, `org_unit.designations_change`, `org_unit.strength_exception` (plus the existing unit events).

## Database migrations introduced (data preserved)
| Migration | Kind | Notes |
|---|---|---|
| `ranks.0002_alter_rank_category` | schema | adds `unspecified` choice |
| `ranks.0003_official_puntland_army_ranks` | data | adds 16 ranks; provisional ranks held by people are **kept inactive**, unused ones deleted. Not reversible. |
| `organization.0002_specialistdesignation_and_more` | schema | 3 tables, 6 columns on units; reversible |
| `organization.0003_puntland_army_structure` | data | template content; tags existing Army regional commands; reversible (no-op) |

Verified on PostgreSQL: a 1.3.0 database with 24 provisional ranks and 8 personnel was upgraded; result: 16 official
ranks, 5 provisional ranks kept inactive because 8 people hold them, 19 unused ones removed, **0 personnel changed**.
`makemigrations --check` is clean; the organization migrations were unapplied and re-applied successfully.

## Tests performed (PostgreSQL 16, Django test runner)
- New: `apps/organization/tests/test_structure.py`, **36 tests, all pass.** They cover the exact 16 names/order, no invented
  translations, idempotent seeding that keeps edits, retirement without orphaning people, template levels and strengths,
  Taliska Guud tagging (Army only), designations not being ranks, level/tier validation, designation and exception rules,
  audit events with from/to, scope isolation (a Bari chief cannot see or change Nugaal), strength needing personnel.view,
  retired/discharged excluded, "no personnel created", findings (two Gaas, Horin Sahan, Urur Sahan/Sanco, non-standard
  parent), catalogue permissions/validation/in-use protection, and the personnel list exposing the unit type.
- Whole backend suite: **174 tests, 166 pass, 8 fail.** All 8 failures are older tests unrelated to this addendum (below).
- Frontend: `tsc --noEmit` clean, `vitest` 3/3 (including English/Somali key parity), `vite build` succeeds.
- **Not done:** no browser or device testing of the new screens (no browser in the build environment), so layout on
  Android and desktop is unverified; Somali UI text is a draft needing translator review.

### Existing failing tests (not caused by, and not touched by, this addendum)
These were failing in the uploaded 1.3.0 as well (the 1.3.0 report says its tests had never been run). I left them alone
because the addendum forbids changing unrelated areas; the causes are known and the fixes are small:
- `test_login_success_and_failure_are_audited`, `test_must_change_password_confines_session_then_releases`: the test helper
  enables MFA on every user, so login needs a code; the tests should pass `mfa=False`.
- Three workflow notification tests query the username `rev-BARI`; usernames are stored lower-case (`rev-bari`).
- `test_only_audit_view_holders_can_read_and_there_is_no_write_api` expects 405, the API answers 403 (deny by default).
- `test_hq_admin_can_add_region_and_unit_inherits_branch` compares a UUID object to a string.
- `test_direct_lookup_and_edit_outside_scope_is_404` expects 404 for PATCH of an out-of-scope unit; the API answers 403
  because editing units needs a global `org.manage` permission the caller lacks (no information leak either way).

## Fixes outside the addendum (please confirm you want them kept)
- `core/exceptions.py`: with the uploaded 1.3.0, any 404 from `get_object()` (for example opening an out-of-scope or unknown
  record) crashed the custom error handler and returned a **500**. The new endpoints depend on correct 404s, so I fixed it
  (12 tests had been failing for this reason).
- `pages/Logistics.tsx`: a type-only annotation, because `npm run build` (`tsc && vite build`) failed on it in 1.3.0.
- `UnitSerializer` now drops DRF's automatic unique validators so duplicate codes report `code_taken` / `hq_exists`.

## Assumptions requiring confirmation
1. Rank names are used exactly as supplied for both languages; "(General)" and "(Marshall)" stay inside the names.
2. The 16 ranks are seeded **approved** (supplied as official) and have no enlisted/warrant/officer split.
3. Rank codes `PA-01`..`PA-16` are internal identifiers.
4. Taliska Guud = the existing Army branch command of each region (not a new unit above it).
5. "Each Gaas has a designated Urur Sahan/Sanco" = one Urur Sahan **and** one Urur Sanco (one unit may be both).
6. "Designated Horin" / "Urur" means anywhere below the Guuto / Gaas, not only direct children.
7. Strength counts personnel still in service (not retired/discharged) in the unit and all units below it.
8. People holding the retired provisional ranks must be re-ranked by an authorised user; no mapping was supplied.
9. Unit types and designations are not limited to the Army branch.

## Files
### Created
- `backend/apps/ranks/catalogue.py` — the 16 official ranks (initial content) and the idempotent apply function
- `backend/apps/ranks/migrations/0002_alter_rank_category.py` — adds the `unspecified` category (schema only)
- `backend/apps/ranks/migrations/0003_official_puntland_army_ranks.py` — data migration: adds the 16 ranks, retires the provisional ones
- `backend/apps/ranks/management/commands/report_rank_remap.py` — counts people still on a retired rank
- `backend/apps/organization/reference.py` — unit types, designations and expected-relationship rules (initial content)
- `backend/apps/organization/structure.py` — reference vs actual strength and template findings (read-only analysis)
- `backend/apps/organization/migrations/0002_specialistdesignation_and_more.py` — schema (3 new tables, new unit columns)
- `backend/apps/organization/migrations/0003_puntland_army_structure.py` — data: template content, Taliska Guud tagging
- `backend/apps/organization/tests/test_structure.py` — 36 new tests
- `frontend/src/pages/Structure.tsx` — Structure page (findings, strength, catalogue management)
- `frontend/src/components/UnitPicker.tsx` — searchable unit selector
- `frontend/src/api/useUnitTypes.ts` — unit type / designation catalogue hook

### Modified
- `backend/apps/ranks/models.py` — `unspecified` category
- `backend/apps/organization/models.py` — UnitType, SpecialistDesignation, DesignationRule; unit_type, designations, strength-exception fields on units
- `backend/apps/organization/serializers.py` — template validation, strength exception stamping, three catalogue serializers
- `backend/apps/organization/views.py` — unit filters (q, unit_type, designation, placeable), catalogue endpoints, structure endpoint, new audit events
- `backend/apps/accounts/serializers.py` — unit brief exposes `unit_type` (id only, no extra query)
- `backend/config/api_v1.py` — 4 new routes under /organization/
- `backend/config/settings.py` — version string only
- `backend/apps/core/management/commands/seed_reference_data.py` — seeds the 16 ranks and the template instead of the US-style list
- `backend/apps/accounts/management/commands/seed_demo_data.py` — demo people use official ranks
- `backend/apps/core/exceptions.py` — FIX: Http404/PermissionDenied from get_object() no longer crash the handler into a 500
- `backend/apps/accounts/tests/test_audit_ranks_org.py, backend/apps/personnel/tests/test_personnel.py, backend/apps/training/tests/test_training.py` — tests that used the provisional rank codes now use the official ones
- `frontend/src/api/types.ts, i18n/en.ts, i18n/so.ts` — new types and strings (en/so parity test passes)
- `frontend/src/App.tsx, components/Layout.tsx` — route and navigation entry "Structure"
- `frontend/src/pages/Organization.tsx` — unit type, designations, strength exception, search, type filter, pagination
- `frontend/src/pages/Personnel.tsx` — searchable unit picker (list filter, create, transfer); unit type shown next to the unit
- `frontend/src/pages/Ranks.tsx` — category filter lists `unspecified`
- `frontend/src/pages/Logistics.tsx` — FIX: type-only annotation; `npm run build` failed on this line in 1.3.0 (runtime unchanged)
- `README.md, CHANGELOG.md, VERSION, frontend/package.json, docs/LIMITATIONS.md, docs/SETUP.md, docs/DEPLOY_ROLLBACK.md`

### Deleted
None.

### Unchanged
Everything else, including authentication, roles and permissions, personnel history/import/export, requests and reports,
logistics, training and audit.

## Next
Version 1.4 (security and reliability hardening) was not part of this addendum. I had started it separately on top of
1.3.0 (and found further issues, e.g. forgeable `X-Forwarded-For` bypassing login throttling, no TOTP replay protection);
that work is parked and not included here.
