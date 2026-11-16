.PHONY: backend frontend test migrate
backend:
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
frontend:
	npm run dev --prefix frontend -- --port 5173
migrate:
	cd backend && .venv/bin/alembic upgrade head
test:
	cd backend && .venv/bin/pytest -q
	npm test --prefix frontend
	npm run build --prefix frontend

.PHONY: start setup acceptance
start:
	./scripts/start.sh
setup:
	./scripts/setup.sh
acceptance:
	backend/.venv/bin/python scripts/acceptance.py

.PHONY: test-unit test-component test-usecase test-functionality
test-unit:
	cd backend && .venv/bin/python -m pytest -q tests/test_units.py
test-component:
	npm test --prefix frontend
test-usecase:
	cd backend && .venv/bin/python -m pytest -q tests/test_usecases.py
test-functionality:
	cd backend && .venv/bin/python -m pytest -q tests/test_foundation.py tests/test_media.py tests/test_integrations.py tests/test_delivery_ai.py
