# Windows version of make-migrations.sh. Needs the .NET 8 SDK and: dotnet tool install -g dotnet-ef
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\src\Duale.Api")
dotnet ef migrations add Initial -o Migrations
Start-Sleep -Seconds 2
dotnet ef migrations add PostgresConstraints -o Migrations
$f = Get-ChildItem Migrations\*_PostgresConstraints.cs | Where-Object { $_.Name -notlike "*Designer*" } | Select-Object -First 1
$t = Get-Content $f.FullName -Raw
$t = [regex]::Replace($t, '(protected override void Up\(MigrationBuilder migrationBuilder\)\s*\{)', "`$1`n            Duale.Api.Data.PostgresConstraints.Up(migrationBuilder);")
$t = [regex]::Replace($t, '(protected override void Down\(MigrationBuilder migrationBuilder\)\s*\{)', "`$1`n            Duale.Api.Data.PostgresConstraints.Down(migrationBuilder);")
Set-Content $f.FullName $t
if ($t -notmatch "PostgresConstraints.Up") { throw "Could not patch $($f.Name); add the two calls by hand." }
Write-Host "Done. Review Migrations/, then run the API with Database__AutoMigrate=true."
