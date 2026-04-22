PYTHON ?= python
PIP ?= pip

.PHONY: help install install-dev run test lint typecheck fmt docker-build docker-up docker-down clean

help:
	@echo "Targets:"
	@echo "  install       Install runtime deps"
	@echo "  install-dev   Install runtime + dev deps"
	@echo "  run           Run the bot locally (requires .env)"
	@echo "  test          Run pytest"
	@echo "  lint          Ruff lint"
	@echo "  typecheck     mypy --strict on app/"
	@echo "  fmt           Ruff format"
	@echo "  docker-build  Build the image"
	@echo "  docker-up     Start bot + postgres + prometheus"
	@echo "  docker-down   Stop the stack"
	@echo "  clean         Remove caches and build artifacts"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

run:
	$(PYTHON) -m app.main

test:
	$(PYTHON) -m pytest -v

lint:
	ruff check app tests scripts

typecheck:
	mypy --strict app

fmt:
	ruff format app tests scripts

docker-build:
	docker build -t advert-bot:latest .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ **/__pycache__
