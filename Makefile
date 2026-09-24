.PHONY: generate baml-smoke lint test sandbox

SANDBOX_DIR ?= .sandbox

generate:
	uv run baml-cli generate

baml-smoke: generate
	uv run pytest -v -rs tests/test_baml_smoke.py

lint:
	uv run ruff check .
	uv run ruff format --check .

test: generate
	uv run pytest -rs

# Build every scenario as a local repo under $(SANDBOX_DIR)/<scenario>
sandbox:
	uv run rebase-sandbox generate --local $(SANDBOX_DIR)
