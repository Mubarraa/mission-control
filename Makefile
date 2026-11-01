.PHONY: up down migrate seed logins install-cli uninstall-cli run test test-unit demo lint fmt

# Docker Desktop installs its CLI in ~/.docker/bin, which is not always on PATH.
DOCKER ?= PATH="$(HOME)/.docker/bin:$$PATH" docker

up:            ## Start Postgres and wait until it is healthy
	$(DOCKER) compose up -d --wait postgres
	@echo "Postgres is healthy on localhost:5433"

down:          ## Stop Postgres and delete its data
	$(DOCKER) compose down -v

migrate:       ## Apply database migrations
	uv run alembic upgrade head

seed:          ## Load demo organisations (safe to re-run)
	uv run mission-control-seed

install-cli:   ## Install `mc` as a command (editable: picks up code changes)
	uv tool install --editable --force ./cli
	@echo "Installed. Now type: mc   (if 'mc' isn't found, run: uv tool update-shell)"

uninstall-cli: ## Remove the installed `mc` command
	uv tool uninstall mission-control-cli

logins:        ## List everyone who can log in (and the demo password)
	uv run mission-control-seed --logins

run:           ## Run the API on http://localhost:8000
	MC_BANNER_URL=http://localhost:8000 uv run uvicorn mission_control.api.app:create_app --factory --reload --port 8000

test:          ## Unit + API + e2e tests (needs `make up`)
	uv run pytest

test-unit:     ## Pure domain tests only (no database)
	uv run pytest tests/unit

demo:          ## Narrated end-to-end journey through `mc` (needs `make run` in another terminal)
	./scripts/demo.sh

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .
