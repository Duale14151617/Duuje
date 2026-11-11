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
Later removed as well: retire_police.py, the Police gate in scope.py and settings.py, the station unit level and the Police rank categories (see CHANGELOG).
Still NOT RUN (no Django here): run the test suite and makemigrations --check.

## CI fixes after the first test run (723 tests, 7 failures)
- test_v2_compatibility: organization migrations 0007-0009 added to the documented list; auditor's payroll.view allowed.
- test_army_structure: name slice [:18] (was [:19], which kept a trailing space).
- seed_demo_data: added transport.officer and vehicle.approver demo accounts (every role needs one).
- test_regional_finance: reconcile uses the statement reference that matches the payment (TX-R1); a mismatch needs a note.
- change_requests: rejecting a batch with an empty note now returns 400 (checked before the loop). The history test picks the transfer row by label, because the record-creation row has today's date and sorts first.
Still not run locally (no Django here): CI is the check.
