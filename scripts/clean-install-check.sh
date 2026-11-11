#!/usr/bin/env bash
# Spec: "perform a clean-install test using only documented deployment steps".
# Builds from nothing (fresh volumes), starts the documented stack and runs the smoke test. Uses the DEV compose file with
# throw-away secrets; the production file is exercised the same way on staging (see docs/ops/deployment.md).
set -euo pipefail
cd "$(dirname "$0")/.."
export DB_PASSWORD="$(openssl rand -hex 16)"
export ADMIN_EMAIL="admin@example.test" ADMIN_PASSWORD="$(openssl rand -hex 12)Aa1!"
cat > .env.clean <<ENV
DB_PASSWORD=$DB_PASSWORD
Jwt__Key=$(openssl rand -hex 32)
Jwt__Issuer=duale-buildlink
Jwt__Audience=duale-buildlink
Database__AutoMigrate=true
Bootstrap__AdminEmail=$ADMIN_EMAIL
Bootstrap__AdminPassword=$ADMIN_PASSWORD
Mfa__Key=$(openssl rand -base64 32)
Files__Root=/data/files
Finance__CallbackSecret=$(openssl rand -hex 16)
Scanner__AllowNoop=true
ENV
trap 'docker compose --env-file .env.clean down -v >/dev/null 2>&1; rm -f .env.clean' EXIT
docker compose --env-file .env.clean down -v >/dev/null 2>&1 || true
docker compose --env-file .env.clean up -d --build
for i in $(seq 1 60); do curl -fs http://localhost:8080/health/ready >/dev/null 2>&1 && break; sleep 2; done
BASE=http://localhost:8080 scripts/smoke.sh
echo "clean install OK"
