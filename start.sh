#!/usr/bin/env bash
# One-command start for Mac/Linux: private Python env on first run, then opens the lead desk.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up, this takes a minute..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "A file called .env was created. Open it, paste your keys, save, then run ./start.sh again."
fi
(sleep 2; (open http://127.0.0.1:8765/ || xdg-open http://127.0.0.1:8765/) >/dev/null 2>&1) &
.venv/bin/python -m app --port 8765
