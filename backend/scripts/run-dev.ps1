# run-dev.ps1 — Activates the venv and starts FastAPI in hot-reload mode.
# Run from the backend/ directory:
#   .\scripts\run-dev.ps1

.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
