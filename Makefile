.PHONY: setup api worker migrate database-check build format format-check lint typecheck \
	test test-python test-web check check-private check-secrets postgres-up postgres-down \
	test-integration

setup:
	uv sync --locked --all-groups --all-extras
	pnpm install --frozen-lockfile

api:
	BILLZEBUB_DEVELOPMENT_IDENTITY=developer@localhost uv run billzebub-api

worker:
	uv run billzebub-worker

migrate:
	uv run billzebub migrate

database-check:
	uv run billzebub check

build:
	pnpm --dir web build

format:
	uv run ruff format src scripts tests
	uv run ruff check --fix src scripts tests
	pnpm --dir web format

format-check:
	uv run ruff format --check src scripts tests
	pnpm --dir web format:check

lint: check-private check-secrets
	uv run ruff check src scripts tests
	pnpm --dir web lint

typecheck:
	uv run mypy
	pnpm --dir web typecheck

test: test-python test-web

test-python:
	uv run pytest $(if $(TEST_DATABASE_URL),,-m "not integration")

test-web:
	pnpm --dir web test

check: format-check lint typecheck test build

check-private:
	uv run python scripts/check_private_files.py

check-secrets:
	bash scripts/check-secrets.sh # pragma: allowlist secret

postgres-up:
	docker compose -f compose.dev.yaml up -d --wait postgres

postgres-down:
	docker compose -f compose.dev.yaml down

test-integration: postgres-up
	TEST_DATABASE_URL=postgresql://billzebub:billzebub-development-only@127.0.0.1:54329/billzebub_test \
		uv run pytest -m integration
