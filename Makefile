.PHONY: generate baml-smoke lint test

generate:
	uv run baml-cli generate

baml-smoke: generate
	uv run pytest -v -rs tests/test_baml_smoke.py

lint:
	uv run ruff check .
	uv run ruff format --check .

test: generate
	uv run pytest -rs
