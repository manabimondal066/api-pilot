# dev-start.ps1 — Start the api-pilot backend dev server.
# Run from anywhere in the project:
#   .\scripts\dev-start.ps1
#
# Prerequisites:
#   - PostgreSQL 18 running locally
#   - backend/.venv created (run .\scripts\install.ps1 once if not done)

Write-Host "=== API Pilot Dev Server ===" -ForegroundColor Cyan
Write-Host ""

# --- Check PostgreSQL ---
$pgBin = "C:\Program Files\PostgreSQL\18\bin"
$pgReady = & "$pgBin\pg_isready.exe" -h localhost -p 5432 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PostgreSQL is not running. Start it first." -ForegroundColor Red
    Write-Host "  Open 'Services' (services.msc) and start 'postgresql-x64-18'" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] PostgreSQL is running" -ForegroundColor Green

# --- Activate venv and start server ---
Set-Location "$PSScriptRoot\..\backend"
.\.venv\Scripts\Activate.ps1
Write-Host "[OK] Virtual environment activated" -ForegroundColor Green
Write-Host ""
Write-Host "Starting uvicorn on http://localhost:8000 ..." -ForegroundColor Cyan
Write-Host "  API docs: http://localhost:8000/docs"     -ForegroundColor Gray
Write-Host "  Health:   http://localhost:8000/api/healthz" -ForegroundColor Gray
Write-Host "  Press Ctrl+C to stop"                     -ForegroundColor Gray
Write-Host ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
