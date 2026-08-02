.PHONY: setup up down logs clean build rebuild ps infra-up infra-down eval-financial export-corrections generate-goldens generate-contracts

all: up

setup:
	@echo "Setting up environment..."
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example — review secrets."; else echo ".env already exists."; fi

build: setup
	@echo "Building product stack..."
	docker compose build

rebuild: setup
	@echo "Rebuilding product stack (no cache)..."
	docker compose build --no-cache

up: setup
	@echo "Starting product stack..."
	docker compose up -d

down:
	@echo "Stopping product stack..."
	docker compose down

clean:
	@echo "Stopping product stack and removing volumes..."
	docker compose down -v

logs:
	docker compose logs -f

ps:
	docker compose ps

infra-up:
	@echo "Starting infra sidecars (ElasticMQ/S3Mock/Cube/Connect/observability)..."
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

generate-contracts:
	cd packages/contracts && npm install && npm run generate

generate-goldens:
	cd apps/schema-aligner && poetry run python evals/generate_goldens.py

eval-financial:
	cd apps/schema-aligner && poetry run python evals/run_eval.py

export-corrections:
	cd apps/agentic-brain && poetry run python scripts/export_corrections.py --validate
