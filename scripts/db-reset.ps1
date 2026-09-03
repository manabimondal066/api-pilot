# db-reset.ps1 — Drop and recreate the api_pilot database, then re-run migrations.
# WARNING: This deletes ALL data!
#
# Run from anywhere in the project:
#   .\scripts\db-reset.ps1

$pgBin = "C:\Program Files\PostgreSQL\18\bin"

Write-Host ""
Write-Host "WARNING: This will delete ALL data in the api_pilot database!" -ForegroundColor Red
Write-Host ""
$confirm = Read-Host "Type 'yes' to continue"
if ($confirm -ne "yes") {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Dropping and recreating api_pilot..." -ForegroundColor Cyan

# Disconnect any open sessions before dropping
& "$pgBin\psql.exe" -h localhost -U postgres -c @"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'api_pilot' AND pid <> pg_backend_pid();
"@

& "$pgBin\psql.exe" -h localhost -U postgres -c "DROP DATABASE IF EXISTS api_pilot;"
& "$pgBin\psql.exe" -h localhost -U postgres -c "CREATE DATABASE api_pilot OWNER api_pilot;"
Write-Host "[OK] Database api_pilot has been reset." -ForegroundColor Green

# Re-run migrations
Write-Host ""
Write-Host "Running migrations..." -ForegroundColor Cyan
Set-Location "$PSScriptRoot\..\backend"
.\.venv\Scripts\Activate.ps1
alembic upgrade head
Write-Host "[OK] Migrations applied." -ForegroundColor Green
