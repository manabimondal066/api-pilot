# dev-test.ps1 — Run the full test suite.
# Run from anywhere in the project:
#   .\scripts\dev-test.ps1

Write-Host "=== API Pilot Tests ===" -ForegroundColor Cyan
Write-Host ""

Set-Location "$PSScriptRoot\..\backend"
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
