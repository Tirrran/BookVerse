#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Не найдено .venv. Сначала выполни: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

# Автозапуск Ollama для гибридного режима (если сервис еще не поднят).
if command -v ollama >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    echo "Ollama уже запущена (127.0.0.1:11434)."
  else
    echo "Запускаю Ollama (127.0.0.1:11434)..."
    nohup ollama serve >/tmp/bookverse-ollama.log 2>&1 &
    for _ in {1..20}; do
      if curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
        echo "Ollama запущена."
        break
      fi
      sleep 0.3
    done
  fi
else
  echo "Ollama не найдена в PATH. Продолжаю без LLM-этапа."
fi

EXISTING_PID="$( (lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null || true) | awk 'NR==2 {print $2}' )"
if [[ -n "${EXISTING_PID:-}" ]]; then
  echo "Порт 8000 занят процессом ${EXISTING_PID}, останавливаю..."
  kill "$EXISTING_PID" || true
  sleep 0.3
fi

echo "Запускаю backend на http://127.0.0.1:8000"
if [[ -f ".env" ]]; then
  exec uvicorn server:app --host 127.0.0.1 --port 8000 --env-file .env
fi

exec uvicorn server:app --host 127.0.0.1 --port 8000
