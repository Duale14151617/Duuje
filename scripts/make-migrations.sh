#!/usr/bin/env bash
# Generates the EF Core migrations. Needs: .NET 8 SDK and `dotnet tool install -g dotnet-ef`. No database required.
set -euo pipefail
cd "$(dirname "$0")/../src/Duale.Api"

dotnet ef migrations add Initial -o Migrations

# Empty migration (the model does not change) that applies the PostgreSQL-only constraints.
# It is created AFTER Initial, so its timestamp sorts after it.
sleep 2
dotnet ef migrations add PostgresConstraints -o Migrations
f=$(ls Migrations/*_PostgresConstraints.cs | grep -v Designer)
perl -0pi -e 's/(protected override void Up\(MigrationBuilder migrationBuilder\)\s*\{)/$1\n            Duale.Api.Data.PostgresConstraints.Up(migrationBuilder);/; s/(protected override void Down\(MigrationBuilder migrationBuilder\)\s*\{)/$1\n            Duale.Api.Data.PostgresConstraints.Down(migrationBuilder);/' "$f"
grep -q "PostgresConstraints.Up" "$f" || { echo "Could not patch $f; add the two calls by hand."; exit 1; }
echo "Done. Review Migrations/, then run the API with Database__AutoMigrate=true."
