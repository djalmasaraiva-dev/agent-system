#!/usr/bin/env bash
# Dev wrapper: runs ADK CLI inside the project venv so structlog / pydantic-settings
# / pyjwt / google-cloud-bigquery etc. are all on path.
#
# Usage:
#   ./dev.sh web         # adk web (playground)
#   ./dev.sh run app     # adk run (interactive CLI)
#   ./dev.sh server      # FastAPI server with hot reload
#   ./dev.sh test        # pytest
#   ./dev.sh lint        # ruff + mypy
#   ./dev.sh shell       # python REPL inside the venv
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

cmd="${1:-web}"
shift || true

case "$cmd" in
  web)     exec uv run adk web "$@" ;;
  run)     exec uv run adk run "${1:-app}" ;;
  server)  exec uv run uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-8081}" --reload ;;
  test)    exec uv run pytest tests/unit/ "$@" ;;
  lint)    uv run ruff check app tests && uv run ruff format --check app tests && exec uv run mypy app ;;
  shell)   exec uv run python "$@" ;;
  *)       exec uv run "$cmd" "$@" ;;
esac
