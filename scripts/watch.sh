#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR/backend"
.venv/bin/python -m alembic upgrade head
PATH="$PWD/.venv/bin:$PATH"
export PATH
exec .venv/bin/python -m app.services.watch_worker
