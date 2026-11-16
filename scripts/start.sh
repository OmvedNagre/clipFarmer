#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"
if [ ! -x backend/.venv/bin/python ]; then
  echo 'Run ./scripts/setup.sh first.' >&2
  exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  npm run build --prefix frontend
fi
cd backend
.venv/bin/alembic upgrade head
echo 'VI ClipForge: http://127.0.0.1:8000 (Ctrl+C to stop)'
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
