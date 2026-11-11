#!/usr/bin/env bash
# Logical backup of the database plus the private files volume, with checksums. Run from cron/systemd on the host.
# Point-in-time recovery (the 15-minute RPO in the spec) needs WAL archiving on the PostgreSQL server or a managed database
# with PITR; this script is the portable baseline and the input to restore-drill.sh.
set -euo pipefail
OUT="${BACKUP_DIR:-/var/backups/duale}/$(date -u +%Y%m%dT%H%M%SZ)"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml}"
mkdir -p "$OUT"
$COMPOSE exec -T db pg_dump -U duale -d duale --format=custom --no-owner > "$OUT/db.dump"
$COMPOSE run --rm --no-deps -T -v "$OUT":/backup --entrypoint tar api -czf /backup/files.tar.gz -C /data/files . 2>/dev/null \
  || docker run --rm -v "$(basename "$PWD")_files":/data/files:ro -v "$OUT":/backup alpine tar -czf /backup/files.tar.gz -C /data/files .
( cd "$OUT" && sha256sum db.dump files.tar.gz > SHA256SUMS )
echo "Backup written to $OUT"
# Ship it OFF the host (object storage / another site) and encrypt it there; keep per your retention decision.
