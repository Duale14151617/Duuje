#!/usr/bin/env bash
# Black-box smoke test against a running deployment. Usage: BASE=https://host ADMIN_EMAIL=.. ADMIN_PASSWORD=.. scripts/smoke.sh
set -euo pipefail
BASE="${BASE:-http://localhost:8080}"
ok() { echo "ok   $1"; }; die() { echo "FAIL $1"; exit 1; }
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health/live")" = 200 ] && ok "live" || die "live"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health/ready")" = 200 ] && ok "ready (database + storage)" || die "ready"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/companies")" = 401 ] && ok "anonymous request refused" || die "anonymous request refused"
curl -sI "$BASE/health/live" | grep -qi '^x-content-type-options: nosniff' && ok "security headers" || die "security headers"
curl -sI "$BASE/health/live" | grep -qi '^server:' && die "server header present" || ok "no server header"
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' -d "{\"email\":\"${ADMIN_EMAIL:?}\",\"password\":\"${ADMIN_PASSWORD:?}\"}" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ] && ok "bootstrap admin can sign in" || die "admin login"
A="Authorization: Bearer $TOKEN"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "$A" "$BASE/me")" = 200 ] && ok "/me" || die "/me"
curl -s -H "$A" "$BASE/platform/integrity" | grep -q '"ok":true' && ok "integrity check clean" || die "integrity check"
curl -s -H "$A" "$BASE/platform/overview" | grep -q verificationQueues && ok "platform overview" || die "overview"
echo "smoke passed"
