---
name: intel-pipeline
description: Run the security_info_bot 3-stage intel pipeline (fetch → analyze → write sheet) for TWCERT or CISA KEV. Use when the user asks to fetch / analyze / write intel, run the pipeline end-to-end, resume from a saved JSON, dry-run, or list saved intermediate files.
---

## When to use

Use this skill whenever the user wants to run any stage of the pipeline, resume from a saved intermediate JSON in `src/data/`, or list locally saved files.

## Prerequisites

- Working directory must be the repo root (`security_info_bot/`)
- `uv sync --activate` must have been run at least once

**Env vars required by operation:**

| Operation | Required vars |
|---|---|
| Full pipeline (real writes) | `USE_FIXTURE_DATA=false` + `GEMINI_API_KEY`, `GOOGLE_SA_JSON_*`, `GOOGLE_SHEET_ID`, `ASSETS_SHEET_ID`; TWCERT also needs `TWCERT_ACCOUNT`, `TWCERT_PASSWORD` |
| `--fetch-only` | TWCERT only: `TWCERT_ACCOUNT`, `TWCERT_PASSWORD` |
| `--analyze-only` (dry) | `GEMINI_API_KEY`; `USE_FIXTURE_DATA=true` works for Sheet reads |
| `--dry-run` | Same as above but no shared resources are written |
| `--list-data` / `--load-*` | None beyond what the target stage needs |

## Decision tree

Map the user's intent to the correct command:

| Intent | Command flags |
|---|---|
| Run full pipeline (default = today) | `--source <twcert\|cisa_kev>` |
| Full pipeline, no Sheet writes | add `--dry-run` |
| Set fetch start date | add `--since YYYY-MM-DD` |
| Cap items for testing | add `--limit N` |
| Stage 1 only (fetch + save) | `--fetch-only` → saves `src/data/{source}_*.json` |
| Stages 1–2 (fetch + analyze, no write) | `--analyze-only` → saves `src/data/analysis_{source}_*.json` |
| Resume from saved fetch JSON (Stage 2+) | `--load-data src/data/<file>.json` |
| Resume from saved analysis JSON (Stage 3) | `--load-analysis src/data/analysis_*.json` |
| List locally saved JSONs | `--list-data` (add `--source <prefix>` to filter, e.g. `analysis_twcert`) |

## Constraints (enforce these strictly)

- `--fetch-only` and `--analyze-only` are **mutually exclusive** — never combine them.
- `--load-*` priority: `--load-analysis` > `--load-data`; each skips all earlier stages.
- `--source` accepts only `twcert` or `cisa_kev` (except with `--list-data`, where it acts as a filename prefix filter).
- Default `--since` = today (TW+8 for TWCERT, UTC for CISA KEV).
- A full run without `--dry-run` writes to shared resources (Google Sheet). Always confirm with the user before running — suggest `--dry-run` first if unsure.

## Command reference

```bash
# Full pipeline
uv run python main.py --source twcert
uv run python main.py --source cisa_kev

# Full pipeline, dry-run (no writes)
uv run python main.py --source twcert --dry-run
uv run python main.py --source cisa_kev --dry-run

# With date range
uv run python main.py --source twcert --since 2026-05-01

# Stage 1 only (save fetch JSON)
uv run python main.py --source twcert --fetch-only
uv run python main.py --source twcert --fetch-only --limit 3

# Stage 1–2 only
uv run python main.py --source cisa_kev --analyze-only --dry-run

# Resume from Stage 2 (skip fetch)
uv run python main.py --source twcert --load-data src/data/twcert_20260521_142416.json

# Resume from Stage 3 (skip fetch + analyze)
uv run python main.py --source twcert --load-analysis src/data/analysis_twcert_20260521_143625.json

# List saved files
uv run python main.py --list-data
uv run python main.py --list-data --source analysis_twcert
```

## After running

- Check `src/data/` for new intermediate JSON files.
- Review logs for errors or warnings (e.g. `GeminiQuotaExhausted`, `TwcertLoginError`).
- For real runs (not dry-run): verify entries appeared in the correct date-tab in the Google Sheet.
