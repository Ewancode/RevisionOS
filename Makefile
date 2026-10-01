COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env
BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help dev down logs migrate migration create-user test test-backend test-frontend \
        lint typecheck fmt api-client check

help:
	@echo "make dev            Start db, redis, api, worker and frontend (Docker)"
	@echo "make down           Stop the stack"
	@echo "make migrate        Apply database migrations"
	@echo "make migration m=.. Create a new Alembic migration"
	@echo "make create-user    Create your account (registration is closed)"
	@echo "make test           Run backend and frontend test suites"
	@echo "make lint           Ruff + ESLint"
	@echo "make typecheck      mypy + tsc"
	@echo "make api-client     Regenerate the typed frontend API client"
	@echo "make check          Everything CI runs"

dev:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

migration:
	$(COMPOSE) run --rm api alembic revision --autogenerate -m "$(m)"

create-user:
	$(COMPOSE) run --rm api python -m scripts.create_user

test: test-backend test-frontend

test-backend:
	$(BACKEND) uv run pytest

test-frontend:
	$(FRONTEND) pnpm test

lint:
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
	$(FRONTEND) pnpm lint

typecheck:
	$(BACKEND) uv run mypy
	$(FRONTEND) pnpm typecheck

fmt:
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .

api-client:
	$(BACKEND) uv run python -m scripts.export_openapi ../frontend/openapi.json
	$(FRONTEND) pnpm gen:api

check: lint typecheck test
