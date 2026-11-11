#!/usr/bin/env bash
# Runs inside the Render image build. If Migrations/ is committed, it is used as is. Otherwise the first-deploy migrations are
# generated from the compiled model and given FIXED ids, so every rebuild produces the same migration ids and an already
# migrated database is left alone. Once the model changes you must commit real migrations (see docs/ops/render.md).
set -euo pipefail
cd "$(dirname "$0")/../src/Duale.Api"
export PATH="$PATH:/tools"

if ls Migrations/*.cs >/dev/null 2>&1; then echo "Using committed migrations."; exit 0; fi

dotnet ef migrations add Initial -o Migrations
sleep 2
dotnet ef migrations add PostgresConstraints -o Migrations
f=$(ls Migrations/*_PostgresConstraints.cs | grep -v Designer)
perl -0pi -e 's/(protected override void Up\(MigrationBuilder migrationBuilder\)\s*\{)/$1\n            Duale.Api.Data.PostgresConstraints.Up(migrationBuilder);/; s/(protected override void Down\(MigrationBuilder migrationBuilder\)\s*\{)/$1\n            Duale.Api.Data.PostgresConstraints.Down(migrationBuilder);/' "$f"
grep -q "PostgresConstraints.Up" "$f" || { echo "Could not patch $f"; exit 1; }

renumber() {
  local name=$1 new=$2 old
  old=$(basename "$(ls Migrations/*_"$name".cs | grep -v Designer)" .cs)
  sed -i "s/$old/${new}_${name}/g" "Migrations/$old.cs" "Migrations/$old.Designer.cs"
  mv "Migrations/$old.cs" "Migrations/${new}_${name}.cs"
  mv "Migrations/$old.Designer.cs" "Migrations/${new}_${name}.Designer.cs"
}
renumber Initial 20260101000000
renumber PostgresConstraints 20260101000100
ls Migrations
