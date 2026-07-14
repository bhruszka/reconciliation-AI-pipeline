# Invoice extraction & reconciliation pipeline

An LLM pipeline that turns unstructured supplier-invoice PDFs into structured
records, scores how much to trust each field, and reconciles the invoices against
outgoing bank payments into an **auto-accept / review / reject** decision.

The original take-home brief lives at [`input/README.md`](input/README.md).

## Where things are

**Docs & deliverables**

| What | Path |
|---|---|
| Design discussion (Task 4) | [`DESIGN.md`](DESIGN.md) |
| Architecture diagram | [`design.drawio.png`](design.drawio.png) |
| Evaluation write-up + failure analysis (Task 2) | [`eval_results/EVAL.md`](eval_results/EVAL.md) |
| Golden labels (Task 2) | [`golden/golden_set.json`](golden/golden_set.json) |
| Eval reports, all models (Task 2) | [`eval_results/`](eval_results/) |
| End-to-end triage output (Task 3) | [`results/20260714_183253_anthropic_claude-haiku-4.5/triage.csv`](results/20260714_183253_anthropic_claude-haiku-4.5/triage.csv) |
| Original brief | [`input/README.md`](input/README.md) |

**Code** (`invoice_ingest/`)

| What | Path |
|---|---|
| Ingest — PDF text + OCR (Task 1) | [`invoice_ingest/ingest.py`](invoice_ingest/ingest.py) |
| Extraction agents, prompts, schema | [`invoice_ingest/parsing/`](invoice_ingest/parsing/) |
| Consensus reconciliation + field comparators | [`invoice_ingest/shared/`](invoice_ingest/shared/) |
| Eval harness — accuracy + grounding | [`invoice_ingest/eval/`](invoice_ingest/eval/) |
| Triage / matcher + end-to-end run (Task 3) | [`invoice_ingest/application/`](invoice_ingest/application/) |
| Tests (mirror the package layout) | [`tests/`](tests/) |

## How it works

Each invoice is read three independent ways and the results are cross-checked, so
confidence comes from *agreement between views*, not from the model's own say-so:

1. **Ingest** (`invoice_ingest.ingest`) — extract the PDF text layer and OCR the
   rendered pages (Tesseract). No LLM.
2. **Extract** — three agents read the same invoice differently (OCR text / PDF
   text / page image) and each returns a strict, typed extraction with a verbatim
   `source_quote` per field. Routing skips the text agents on an image-only PDF.
3. **Reconcile** — build a consensus per field: a value is only trusted when two
   views agree; each value is grounded by checking its quote appears in the source.
4. **Triage** (`invoice_ingest.application.matcher`) — two independent scores drive
   the decision: **match** (identity: invoice-id in the bank reference + fuzzy
   company match) and **approval** (reconciliation: exact amount + in-window date).

A separate **eval harness** (`invoice_ingest.eval`) runs a hand-labeled golden set
through every view and reports accuracy and grounding as separate concerns.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14, plus Tesseract with the
Danish/German/English language data (invoices are in all three).

```sh
brew install tesseract tesseract-lang   # macOS; provides dan/deu/eng
make install                            # uv sync (app + dev tools)
cp .env.example .env                    # then fill in the values below
```

## Configuration

All configuration is environment variables, loaded from `.env` at startup by
[`invoice_ingest/config.py`](invoice_ingest/config.py) (real env vars win over the
file). See [`.env.example`](.env.example) for a template.

| Variable | Required | Purpose |
|---|---|---|
| `LLM_API_KEY` | yes | API key for any OpenAI-compatible endpoint (e.g. OpenRouter). |
| `LLM_URL` | yes | Base URL, e.g. `https://openrouter.ai/api/v1`. |
| `LLM_MODEL` | yes | Model slug the endpoint serves, e.g. `anthropic/claude-sonnet-4.5`. Override per run with `MODEL=…`. |
| `TESSDATA_PREFIX` | yes | Path to Tesseract language data (`dan`/`deu`/`eng`). |
| `OCR_LANGS` | no | OCR languages (default `dan+deu+eng`). |
| `OCR_RENDER_DPI` | no | Page render DPI for OCR + the vision agent (default `300`). |
| `LOG_LEVEL` | no | Logging verbosity (default `INFO`; try `DEBUG` or `WARNING`). |

The pipeline is provider-agnostic: point `LLM_*` at OpenRouter, OpenAI, or a local
gateway. Logs go to **stderr**; report tables go to **stdout**, so
`make run > report.txt` captures just the report while progress streams live.

## Usage — the Makefile

`make` (or `make help`) lists every target.

| Target | What it does |
|---|---|
| `make install` | `uv sync` — set up the environment (app + dev tools). |
| `make run` | **End-to-end**: `input/pdf_invoices/` → ingest → extract → triage, written to a fresh `results/<timestamp>/`. |
| `make eval` | Run the golden set through all views; write a timestamped accuracy/grounding report to `eval_results/`. |
| `make report` | Print the most recent eval report (`REPORT=path` to pick one). |
| `make test` | Run the unit tests (pure non-LLM logic). |
| `make lint` | `ruff check`. |
| `make typecheck` | `mypy`. |
| `make check` | `lint` + `typecheck` + `test`. |
| `make clean` | Remove loose top-level artifacts. |

Pick the model per invocation without editing `.env`:

```sh
make run  MODEL=anthropic/claude-opus-4.8
make eval MODEL=openai/gpt-4o
```

### `make run` output

Each run writes `results/<YYYYMMDD_HHMMSS>_<model>/`:

- `ingested.jsonl` — OCR + PDF text per invoice
- `extractions.jsonl` — every agent view's structured extraction
- `triage.csv` — one row per invoice: extracted fields, the **match** and
  **approval** confidences, the decision, and a reason summary for each score

## Layout

```
input/            provided data — PDFs, bank_transactions.csv, invoices.csv, brief
golden/           self-contained golden set (labels + copies of the labeled PDFs)
results/          one timestamped folder per `make run`
eval_results/     timestamped eval reports
invoice_ingest/
  ingest.py         Task 1 — PDF text + OCR
  parsing/          the three extraction agents, prompts, schemas, LLM transport
  shared/           field comparators + consensus reconciliation
  eval/             golden-set harness: accuracy + grounding scoring, reports
  application/      end-to-end run orchestration + matcher/triage
tests/            pytest suite mirroring the package layout (non-LLM logic)
```

## Development

`make check` runs ruff, mypy, and the pytest suite. Tests cover the non-LLM logic
(comparators, consensus, scoring, routing, report/CSV assembly) plus the extraction
error-record contract — a bad PDF or a failed model call yields an error record
rather than crashing the run — and mirror the package layout under `tests/`.
