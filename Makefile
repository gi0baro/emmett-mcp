.DEFAULT_GOAL := all
pysources = emmett_mcp

.PHONY: format
format:
	ruff check --fix $(pysources)
	ruff format $(pysources)

.PHONY: lint
lint:
	ruff check $(pysources)
	ruff format --check $(pysources)

.PHONY: all
all: format lint
