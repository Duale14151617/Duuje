# Merge notes

Root-level `apps/`, `config/` and `src/` were merged into `backend/` and `frontend/`, then removed.

- Copied from root (additive): payroll/regional.py, test_regional_finance.py, test_demo_coverage.py, army_structure.py (+test), seed_demo_data.py, test_breakglass.py, test_death_record.py
- Taken from root (regional scoping): payroll/views.py, payroll/views_ext.py
- Taken from root (break-glass for death confirmation): personnel/death.py
- Hand-merged: seed_reference_data.py keeps backend's vehicles/tasks/changes/food, plus root's regional versions of auditor, payroll_officer, payroll_approver, payment_officer, payment_reconciler
- Kept backend's: accounts/scope.py (GATED_PREFIXES), config/settings.py (apps.vehicles), all frontend/src
- Deleted as identical: access_report, ammunition, payments, review, services, weapons/*, test_police_scope, test_access_report

NOT RUN: Django was unavailable here. Files compile (py_compile) only. Run `python manage.py makemigrations --check` and the test suite before trusting this.

Security note: BREAK_GLASS_ENABLED defaults to True in settings. Death confirmation can now be self-confirmed by a super_admin with a written reason (audited). Consider defaulting ARMYHQ_BREAK_GLASS to off in production.

## Police cleanup
Removed (archived in police-archive.zip): police.py, police_structure.py, police_appointments.py, police_catalogue.py, apply_police_structure and approve_police_ranks commands, five test_police_* files, three Police docs, pmpf.jpg and puntland-police.jpg (root and frontend/public), remove_police_files.sh.
Kept on purpose: retire_police.py (the Dockerfile runs it at start-up), the POLICE_MODULE_ENABLED=False gate in scope.py and settings.py, migrations, the "station" unit level, and two i18n error keys. Removing any of these would need a migration or would expose old Police rows in existing databases.
Added: accounts/tests/test_retired_police_gate.py (two tests that keep guarding the gate; builds its own minimal Police fixture).
Still NOT RUN (no Django here): run the test suite and makemigrations --check.
