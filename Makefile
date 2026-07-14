# Invoice extraction + eval + triage pipeline.
# Everything runs through `uv run`. Override MODEL to switch LLM, e.g.:
#   make run MODEL=anthropic/claude-opus-4.8

MODEL ?=
model_flag = $(if $(MODEL),--model $(MODEL),)

# Model sweep for `run-all` / `eval-all` (cheap/mid/expensive × Anthropic/OpenAI).
MODELS ?= anthropic/claude-haiku-4.5 anthropic/claude-sonnet-5 anthropic/claude-opus-4.8 \
          openai/gpt-5.6-luna openai/gpt-5.6-terra openai/gpt-5.6-sol

.DEFAULT_GOAL := help
.PHONY: help install run run-all eval eval-all report test lint typecheck check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Sync the uv environment (incl. dev tools)
	uv sync

run: ## E2E — PDFs -> ingest -> extract -> triage into results/<timestamp>_<model>/
	uv run python -m invoice_ingest.application $(model_flag)

run-all: ## Full e2e pipeline for every model in MODELS
	@for m in $(MODELS); do echo "########## $$m ##########"; $(MAKE) run MODEL=$$m; done

eval: ## Task 2 — run the golden set, write a timestamped report to eval_results/
	uv run python -m invoice_ingest.eval $(model_flag)

eval-all: ## Golden-set eval for every model in MODELS
	@for m in $(MODELS); do echo "########## $$m ##########"; $(MAKE) eval MODEL=$$m; done

N ?= 1
report: ## Print the last N eval reports (N=3), or REPORT=path for a specific one
	uv run python -m invoice_ingest.eval.report $(or $(REPORT),$(shell ls -t eval_results/eval_*.json 2>/dev/null | head -n $(N)))

test: ## Run the unit tests (non-LLM logic)
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check .

typecheck: ## Type-check with mypy
	uv run mypy

check: lint typecheck test ## Lint + type-check + test

clean: ## Remove loose top-level artifacts (keeps golden/, eval_results/, results/)
	rm -f triage.jsonl
