# install.ps1 — Creates the venv and installs all dependencies (including dev extras).
# Run from the backend/ directory:
#   .\scripts\install.ps1

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
