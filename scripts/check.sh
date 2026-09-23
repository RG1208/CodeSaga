#!/usr/bin/env bash
# Run every static check, test and build that CI would run.
# Requires `scripts/setup.sh` to have been run once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Backend: lint"
(cd "$ROOT/backend" && .venv/bin/ruff check . && .venv/bin/ruff format --check .)

echo "==> Backend: tests"
(cd "$ROOT/backend" && .venv/bin/pytest)

echo "==> Frontend: lint"
(cd "$ROOT/frontend" && npm run lint)

echo "==> Frontend: typecheck"
(cd "$ROOT/frontend" && npm run typecheck)

echo "==> Frontend: production build"
(cd "$ROOT/frontend" && npm run build)

echo "All checks passed."
