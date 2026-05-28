# CLAUDE.md

Automated threat-intel pipeline: fetches TWCERT and CISA KEV daily, runs Gemini AI analysis, writes results to Google Sheets, and archives all artefacts to a dedicated git branch. For specifics, follow the documentation index below.

## Commands

```bash
# Install dependencies
uv sync --activate

# Run tests
uv run pytest tests/ -v

# Dry-run without writing to Sheet or committing archive
uv run python main.py --source cisa_kev --dry-run
uv run python main.py --source twcert --dry-run

# Fetch and save locally without analysis (no Gemini/Sheet credentials needed)
# Both sources default to today; use --since YYYY-MM-DD to change the start date
uv run python main.py --source cisa_kev --fetch-only
uv run python main.py --source twcert --fetch-only --since 2026-05-01

# Limit items for quick testing
uv run python main.py --source twcert --fetch-only --limit 3

# Stage 1+2: fetch + analyze, save both JSONs automatically (default)
uv run python main.py --source twcert --analyze-only

# Stage 2: analyze from a saved fetch JSON
uv run python main.py --source twcert --load-data src/data/twcert_<ts>.json --analyze-only --dry-run

# Stage 3: write Sheet from a saved analysis JSON
uv run python main.py --source twcert --load-analysis src/data/analysis_twcert_<ts>.json --dry-run

# Disable auto-save of intermediate files
uv run python main.py --source cisa_kev --dry-run --no-save-data

# List locally saved intermediate files (prefix filters: twcert, analysis_twcert, etc.)
uv run python main.py --list-data
uv run python main.py --list-data --source analysis_twcert

# Lint + format (ruff)
uv run ruff check .
uv run ruff check --fix .
uv run ruff format .
uv run ruff format --check .
```

## Documentation Index

- [Architecture](docs/architecture.md) — 3-stage pipeline, subsystem map, multi-CVE fan-out, fixture mode, timezone contract
- [Data Models](docs/data-models.md) — `IntelItem` / `AnalysisResult` / `SheetRow` / Gemini schema / Sheet columns A–U
- [Configuration](docs/configuration.md) — env var reference, SA credential resolution, fixture mode files
- [Archive Branch](docs/archive-branch.md) — git worktree mechanics, `{source}/{YYYY-MM}/` layout, IoC URL backfill
- [Deployment Guide](docs/deployment-guide.md) — 首次部署操作指引：GCP SA、Sheets 分享、Gemini Key、TWCERT、GitHub Secrets
- [Deployment](docs/deployment.md) — CI workflows, daily schedule, GitHub Secrets, permissions, self-hosted runner
- [Error Handling](docs/error-handling.md) — `TwcertLoginError` / `GeminiQuotaExhausted`, retry/backoff, `send_ops_alert` (log-only)
- [Original Design Proposal (zh-TW, historical)](docs/spec/資安情資_AI_自動化分析計劃.md)
