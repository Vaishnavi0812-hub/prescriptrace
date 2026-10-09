# Common tasks (Linux/macOS/WSL/Git Bash). On Windows PowerShell use scripts/dev.ps1 instead.
.PHONY: up down logs migrate test test-backend test-frontend lint fmt shell-db

up:            ## Build and start db + backend + frontend
	docker compose up -d --build

down:          ## Stop everything (data volume is kept)
	docker compose down

logs:
	docker compose logs -f backend frontend

migrate:       ## Apply database migrations
	docker compose run --rm backend alembic upgrade head

test: test-backend test-frontend

test-backend:
	docker compose run --rm backend pytest -q

test-frontend:
	cd frontend && npm test

lint:
	docker compose run --rm --no-deps backend sh -c "ruff check . && ruff format --check . && mypy app"
	cd frontend && npm run lint && npm run typecheck

fmt:
	docker compose run --rm --no-deps backend sh -c "ruff check --fix . && ruff format ."

shell-db:
	docker compose exec db psql -U prescriptrace -d prescriptrace
