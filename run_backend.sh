#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Не найдено .venv. Сначала выполни: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

export BOOKVERSE_DISABLE_AUTH="${BOOKVERSE_DISABLE_AUTH:-true}"
export BOOKVERSE_ALGO_ONLY="${BOOKVERSE_ALGO_ONLY:-false}"
export BOOKVERSE_LOCAL_LLM_ENABLED="${BOOKVERSE_LOCAL_LLM_ENABLED:-true}"
export BOOKVERSE_LOCAL_LLM_BASE_URL="${BOOKVERSE_LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434}"
export BOOKVERSE_LOCAL_LLM_MODEL="${BOOKVERSE_LOCAL_LLM_MODEL:-gemma3:1b}"
export BOOKVERSE_LOCAL_LLM_FALLBACK_MODELS="${BOOKVERSE_LOCAL_LLM_FALLBACK_MODELS:-gemma3:1b}"
export BOOKVERSE_LOCAL_LLM_TIMEOUT_SEC="${BOOKVERSE_LOCAL_LLM_TIMEOUT_SEC:-90}"

EXISTING_PID="$( (lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null || true) | awk 'NR==2 {print $2}' )"
if [[ -n "${EXISTING_PID:-}" ]]; then
  echo "Порт 8000 занят процессом ${EXISTING_PID}, останавливаю..."
  kill "$EXISTING_PID" || true
  sleep 0.3
fi

echo "Запускаю backend на http://127.0.0.1:8000"
exec uvicorn server:app --host 127.0.0.1 --port 8000
