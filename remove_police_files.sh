#!/bin/sh
# Run from the project root AFTER unzipping Duuje-army-only.zip over your repo.
# Unzipping adds and replaces files but never deletes, so the old Police files must be removed by hand.
# They are all saved in police-archive.zip.
git rm -f --ignore-unmatch \
  backend/apps/accounts/tests/test_police_scope.py \
  apps/accounts/tests/test_police_scope.py \
  backend/apps/organization/management/commands/apply_police_structure.py \
  backend/apps/organization/police.py \
  backend/apps/organization/police_structure.py \
  backend/apps/organization/tests/test_police_structure.py \
  backend/apps/personnel/police_appointments.py \
  backend/apps/personnel/tests/test_police_appointments.py \
  backend/apps/personnel/tests/test_police_law.py \
  backend/apps/personnel/tests/test_police_records.py \
  backend/apps/ranks/management/commands/approve_police_ranks.py \
  backend/apps/ranks/police_catalogue.py \
  docs/POLICE_LAW_1972_MAPPING.md docs/POLICE_MODULE.md docs/DEPLOYMENT_CHECKLIST.md \
  puntland-police.jpg pmpf.jpg frontend/public/puntland-police.jpg frontend/public/pmpf.jpg
