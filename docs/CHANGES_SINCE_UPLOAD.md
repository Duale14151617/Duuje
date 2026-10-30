# Changes made after the original upload

None of this has been built, linted or tested in a real environment (no npm registry or database was reachable). Run the checks in
"Before you deploy" first.

## 1. Responsive sidebar (frontend)
Drawer below 768px (hamburger + one close button, backdrop, Escape, scroll lock, focus handling); icon-only rail 768-959px;
full sidebar from 960px with one collapse/expand button (choice remembered). Fixed the generic `.icon-btn` rule overriding the
hide rules. Dashboard cards: 2 columns on phones, 4 from 720px, `minmax(0,1fr)`.
Files: `frontend/src/components/Layout.tsx`, `useMedia.ts`, `Icon.tsx`, `src/styles.css`, `src/i18n/{en,so,so_improved}.ts`, `e2e/smoke.spec.ts`.

## 2. Demo accounts
`demo.` prefix removed from usernames (existing accounts are renamed in place); Karkaar, Nugaal and Mudug get the same regional
set as Bari. File: `backend/apps/accounts/management/commands/seed_demo_data.py`.

## 3. Test personnel (removable)
150 synthetic people (`TST-0001...`) with unique Somali names, varied ranks, full identity profile and placeholder photos.
`ARMYHQ_TEST_PERSONNEL=150` adds them on deploy; `0`/unset deletes them all. Files: `backend/apps/personnel/management/commands/seed_test_personnel.py`,
`backend/apps/personnel/tests/test_seed_test_personnel.py`, `Dockerfile`, `RENDER_DEPLOY_GUIDE.md`.

## 4. Police module (pilot, OFF by default) - see docs/POLICE_MODULE.md
`POLICE_MODULE_ENABLED=1` turns it on. Draft Police rank catalogue from Article 23 (1972), seven Police departments with CID as a
restricted unit, `cid.access`, `police.cross_access` and `search.cross_service` permissions, roles `cid_officer` and
`command_authority`, Army/branch-less roles blocked from Police records, cross-service search page.
Backend: `config/settings.py`, `apps/ranks/{models.py,police_catalogue.py,migrations/0005_*}`,
`apps/organization/{models.py,police.py,migrations/0005_*}`, `apps/accounts/{scope.py,tests/test_police_scope.py}`,
`apps/core/management/commands/seed_reference_data.py`, `apps/personnel/views.py`.
Frontend: `src/pages/{CrossSearch,Ranks}.tsx`, `src/App.tsx`, Layout/Icon/i18n as above.

## Before you deploy
1. `cd frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build`
2. `cd backend && python manage.py makemigrations --check && python manage.py test` (the two new migrations were written by hand)
3. Tag the current Army-only code in git (e.g. `army-only-fallback`) before merging.
4. Env vars on Render (all optional): `POLICE_MODULE_ENABLED`, `ARMYHQ_TEST_PERSONNEL`.

## Remaining work
* Police personnel file: disciplinary history, service documents (sensitive, permissioned, audited, with screens).
* Combined cross-service reports; duplicate-identity checks across services; Police stations.
* Approve the Police ranks after review against current Puntland rules; supply General Officer ranks if any; verify Somali labels
  and department names; add Police sample personnel for demos.
* Police entries in the frontend demo-mode mock (`frontend/src/demo/mock.ts`) and a README for the current stack.
* Run the Playwright responsive tests with a test account; fix whatever the first real build and test run turns up.
