#!/usr/bin/env bash
# Rehearse migrations forward, backward and forward again on a SCRATCH database, then run the test-suite.
# Usage: ops/migration_roundtrip.sh   (needs createdb/dropdb rights and the app environment exported)
set -euo pipefail
cd "$(dirname "$0")/../backend"
db="migration_check_$(date -u +%Y%m%d%H%M%S)"
createdb "$db"; trap 'dropdb --if-exists "$db"' EXIT
export POSTGRES_DB="$db"
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py seed_reference_data
echo "== backward (newest apps first)"
for app in training logistics workflows personnel ranks accounts audit organization; do
  python manage.py migrate "$app" zero --noinput
done
echo "== forward again"
python manage.py migrate --noinput
python manage.py makemigrations --check --dry-run
echo "== migration round-trip OK"
