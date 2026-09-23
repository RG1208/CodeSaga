#!/usr/bin/env bash
# One-time local setup: creates .env, the backend virtualenv (with all Python
# packages) and installs the frontend's npm packages.
#
# It does NOT create the PostgreSQL user/database — do that first
# (README.md, "One-time setup", step 1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v git >/dev/null 2>&1; then
  echo "!! git is not installed. CodeSage needs it to clone repositories."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "==> Backend: creating virtualenv and installing dependencies"
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip >/dev/null
backend/.venv/bin/pip install -r backend/requirements-dev.txt

echo "==> Backend: applying database migrations"
if ! (cd backend && .venv/bin/alembic upgrade head); then
  echo "!! Migrations failed. Is PostgreSQL running, and do the user/database in"
  echo "   DATABASE_URL (.env) exist? Fix that, then run: cd backend && .venv/bin/alembic upgrade head"
fi

echo "==> Frontend: installing packages"
(cd frontend && npm install)

cat <<'DONE'

Setup complete. Run the app in two terminals:

  Terminal 1 (backend):   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
  Terminal 2 (frontend):  cd frontend && npm run dev

Then open http://localhost:3000
DONE
