#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first (macOS: brew install ffmpeg; Ubuntu: apt install ffmpeg).'; exit 1; }
command -v ffprobe >/dev/null || { echo 'FFprobe is required.'; exit 1; }
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock.txt
backend/.venv/bin/python -m pip install --no-deps -e 'backend[dev]'
npm ci --prefix frontend
npm run build --prefix frontend
[ -f .env ] || cp .env.example .env
cd backend
.venv/bin/python -m alembic upgrade head
echo 'Setup complete. Run ./scripts/start.sh.'
