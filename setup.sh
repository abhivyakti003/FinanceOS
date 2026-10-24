#!/usr/bin/env bash
# macOS / Linux setup
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3.13 || command -v python3)
"$PY" -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
[ -f .env ] || python scripts/configure.py
python -m app.database.init_db
echo "All set. Start with: ./run.sh"
