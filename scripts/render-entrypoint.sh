#!/bin/sh
# Render mounts the persistent disk owned by root; fix ownership, then drop privileges for the app.
set -e
mkdir -p "${Files__Root:-/data/files}"
chown -R 10001:10001 "${Files__Root:-/data/files}" 2>/dev/null || true
exec setpriv --reuid=10001 --regid=10001 --clear-groups dotnet Duale.Api.dll
