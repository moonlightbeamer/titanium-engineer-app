.PHONY: test lint run migrate install

install:
	uv sync --extra dev

test:
	uv run pytest tests/ -v --cov=pr_reviewer --cov-report=term-missing

test-unit:
	uv run pytest tests/unit/ -v -m unit

test-integration:
	uv run pytest tests/integration/ -v -m integration

test-e2e:
	uv run pytest tests/e2e/ -v -m e2e

lint:
	uv run ruff check pr_reviewer/ tests/
	uv run ruff format --check pr_reviewer/ tests/

lint-fix:
	uv run ruff check --fix pr_reviewer/ tests/
	uv run ruff format pr_reviewer/ tests/

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

run:
	uv run uvicorn pr_reviewer.api.main:app --host 0.0.0.0 --port 8000 --reload

run-worker:
	uv run celery -A pr_reviewer.workers worker -Q review_jobs --concurrency 10 --loglevel info

run-feedback-worker:
	uv run celery -A pr_reviewer.workers worker -Q feedback_jobs --concurrency 4 --loglevel info

services-up:
	podman compose up -d

services-down:
	podman compose down
