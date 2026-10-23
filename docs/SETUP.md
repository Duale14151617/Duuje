# Setup (development)

Requirements: Python 3.11+, Node 20+, PostgreSQL 15+ (or SQLite for quick local/test runs).

## Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Option A - PostgreSQL (docker compose up -d db from the repo root, then create the app role: see DEPLOY_ROLLBACK.md)
# Option B - SQLite, development only:
export DJANGO_DEBUG=1 USE_SQLITE=1

python manage.py makemigrations --check   # migrations were hand-written; this must report "No changes detected"
python manage.py migrate
python manage.py createcachetable         # login throttling cache
python manage.py seed_reference_data      # permissions, roles, branches, regions, DRAFT ranks (idempotent)
python manage.py apply_police_structure --apply  # Police commands, departments, stations (only when POLICE_MODULE_ENABLED=1)
python manage.py apply_army_structure --apply   # Army HQ, directorates, 4 regional commands, Guuto/Urur and battalion sections (idempotent, additive)

# First real administrator (prompts for a password; first login forces password change + MFA enrolment)
python manage.py create_hq_admin --username admin --full-name "System Administrator"

# Optional synthetic demo accounts (DEBUG only)
export ARMYHQ_DEMO_PASSWORD='choose-a-12+-char-password'
python manage.py seed_demo_data

python manage.py runserver
```
Demo users: `hqadmin`, `hqreports`, `auditor`, `bari.chief`, `nugaal.chief`,
`bari.armyadmin`, `bari.unitadmin`, `logistics`, `readonly`. Karkaar, Nugaal and Mudug each have the same regional set
as Bari, named `<region>.chief`, `.armyadmin`, `.unitadmin`, `.reporter`, `.logistics`, `.restricted`, `.trainer`
(for example `karkaar.chief`, `mudug.reporter`). Privileged ones must enrol
an authenticator app (TOTP) at first sign-in. Compare what each user can see to check scoping.

Personnel needs approved ranks. In a demo, `seed_demo_data` approves a few Army ranks with placeholder Somali names
(demo only). In real use an administrator approves ranks in the Ranks screen after supplying Somali names.
Export: set `PERSONNEL_EXPORT_ENABLED=1` only after institutional approval.

Reports: re-run `seed_reference_data` after upgrading (adds permissions, role grants and the three starter report types).
Summary export: set `REPORT_EXPORT_ENABLED=1` only after institutional approval. Demo user `bari.reporter` can submit;
`bari.chief` can review; `hqreports` sees summaries.

Logistics/training: re-run `seed_reference_data` after upgrading (new permissions, two new roles, draft categories and
starter courses). Categories must be approved by a `logistics_reviewer` (never the creator) before use. In a demo,
`seed_demo_data` approves two harmless categories and adds sample stock/vehicles; demo users: `logistics`,
`restricted`, `reviewer`, `trainer`.

Hardening (1.4): `python manage.py check --deploy --fail-level ERROR` must pass in production. Password recovery: an
administrator issues a one-time code from the user's page; the user opens `/reset`, enters username + code + new password.
Operations: `docs/RUNBOOK.md`, scripts in `ops/`. Evidence log and open checks: `docs/TEST_PLAN_1.4.md`.

## Frontend
```bash
cd frontend
npm install        # creates package-lock.json - commit it
npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run typecheck && npm run lint && npm test
npx playwright install chromium && npm run e2e   # layout/accessibility smoke (needs the stack running)
```

## Tests
```bash
cd backend
DJANGO_DEBUG=1 USE_SQLITE=1 python manage.py test apps            # fast
# Against PostgreSQL (recommended before release; exercises constraints/trigger):
DJANGO_DEBUG=1 POSTGRES_PASSWORD=... python manage.py test apps
```

Structure changes: assign the *Structure approver* role (HQ) to someone other than the proposer; see `docs/STRUCTURE_APPROVAL.md`.
Analytics: sign in as a role holding `analytics.view` (hq_reporting, regional_chief, branch_admin) after `seed_reference_data`.
Integrations: set `INTEGRATIONS_ENABLED=1` only after institutional approval; see `docs/INTEGRATIONS.md`.
