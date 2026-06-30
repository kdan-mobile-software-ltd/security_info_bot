# Architecture

Automated threat-intel pipeline that fetches from two sources daily, runs Gemini analysis, and writes structured rows to Google Sheets. Intermediate artefacts (fetch JSON, analysis JSON, IoC txt) are committed to a dedicated git archive branch.

## Directory structure

```
├── main.py                          # CLI entry point — stage_fetch / stage_analyze / stage_write_sheet
├── pyproject.toml
├── .env.example                     # env var template
├── .github/workflows/
│   ├── twcert.yml                   # daily 09:00 TW+8
│   └── cisa_kev.yml                 # daily 09:00 TW+8
├── src/
│   ├── config.py                    # all env vars + SA credential resolution
│   ├── models.py                    # IntelItem / AnalysisResult / SheetRow
│   ├── fetchers/
│   │   ├── twcert.py                # TWCERT REST API client + xlsx IoC parser
│   │   ├── cisa_kev.py              # CISA KEV JSON feed fetcher
│   │   └── storage.py               # save_items / load_items / save_analysis / load_analysis
│   ├── analyzer/
│   │   ├── gemini.py                # Gemini API call + ANALYSIS_SCHEMA + retry logic
│   │   └── prompt.py                # SYSTEM_PROMPT + build_analysis_prompt()
│   ├── sinks/
│   │   ├── sheets.py                # gspread write + monthly tab auto-create + dedup + asset context
│   │   └── git_archive.py           # worktree commit + IoC URL derivation
│   ├── parsers/
│   │   └── ioc_xlsx.py              # base64 xlsx → (ips, hashes, domains) + write_ioc_txt()
│   ├── notifiers/
│   │   ├── email.py                 # SMTP sender (STARTTLS) — send_risk_digest / send_internal_announcement
│   │   └── templates.py             # Jinja2 HTML renderers — render_risk_digest / render_internal_cards
│   └── utils/
│       ├── logging.py               # structured log singleton
│       └── errors.py                # TwcertLoginError / GeminiQuotaExhausted / send_ops_alert
├── tests/
│   ├── fixtures/
│   │   ├── sample_assets.json       # fixture asset inventory (8-column format)
│   │   ├── sample_cisa_kev.json     # fixture CISA KEV feed
│   │   └── sample_twcert_iocs.xlsx  # fixture IoC attachment for parser tests
│   ├── test_cisa_kev_fetcher.py
│   ├── test_ioc_parser.py
│   ├── test_sheet_writeback.py
│   ├── test_storage.py
│   └── test_twcert_since.py
└── docs/
    ├── architecture.md              # ← this file
    ├── data-models.md
    ├── configuration.md
    ├── archive-branch.md
    ├── deployment.md
    ├── error-handling.md
    └── spec/                        # historical zh-TW design proposal
```

## Pipeline stages

```
Stage 1 Fetch  →  Stage 2 Analyze  →  Stage 3 Write Sheet
      ↓                  ↓
{source}/{YYYY-MM}/      {source}/{YYYY-MM}/          git archive branch (data)
  {source}_*.json          analysis_{source}_*.json     + IoC URL → Sheet col H

                                              ↓ (decoupled, Cloud Run Jobs)
                                    Stage 4a --notify-risk  (monthly)
                                      Reads Sheet rows where company_relevance ≠ 無
                                      → renders risk-team digest HTML
                                      → sends via SMTP to RISK_TEAM_EMAILS

                                    Stage 4b --publish-internal  (on-demand / scheduled)
                                      Scans Sheet rows where 狀態 = 核可發佈 & 通知時間 空
                                      → renders internal announcement HTML cards
                                      → emails INTERNAL_ANNOUNCE_EMAILS (RD managers)
                                      → stamps S「通知時間」on each sent row
```

Stages 1–3 are independently re-runnable via `--fetch-only`, `--analyze-only`, `--load-data`, and `--load-analysis` CLI flags. Each stage saves its output to `src/data/` locally and commits it to the archive branch (when `GIT_ARCHIVE_BRANCH` is set).

Stages 4a and 4b are **decoupled from the daily fetch pipeline** and run as **Cloud Run Jobs** triggered by Cloud Scheduler. See [cloudrun-deploy.md](cloudrun-deploy.md) §10 for deployment details. Both stages support `--dry-run` (no email sent, HTML previewed to `src/data/`) and operate independently of each other.

## Subsystems

### `src/fetchers/`

| File | Role |
|:--|:--|
| `twcert.py` | REST API client — logs in to the TWCERT enterprise portal, paginates intel list, fetches per-item detail. Parses `infoFile` base64 xlsx attachments for IoC extraction. Raises `TwcertLoginError` on auth failure. Default `--since`: today TW+8. |
| `cisa_kev.py` | Fetches the CISA Known Exploited Vulnerabilities JSON feed; filters entries where `dateAdded >= since_date`. Default `--since`: today UTC. |
| `storage.py` | `save_items` / `load_items` / `save_analysis` / `load_analysis` — serialise `IntelItem` and `AnalysisResult` lists to/from JSON files under `src/data/`. |

### `src/analyzer/`

| File | Role |
|:--|:--|
| `gemini.py` | Calls Gemini via the `google-genai` SDK with `ANALYSIS_SCHEMA` (structured JSON output, enforced enums). Retries on 429/5xx with exponential backoff; raises `GeminiQuotaExhausted` after `max_retries=3`. |
| `prompt.py` | `SYSTEM_PROMPT` — analysis principles, risk-level rules, output schema doc. `build_analysis_prompt(intel_content, assets_context)` — assembles the per-item user turn. |

### `src/sinks/`

| File | Role |
|:--|:--|
| `sheets.py` | `append_rows` writes `SheetRow` lists to per-month Google Sheets worksheets (named `YYYY-MM`); auto-creates tabs on first use. `get_existing_intel_ids` scopes dedup per month. `load_assets_context` loads the asset inventory from an external sheet (`ASSETS_SHEET_ID`). |
| `git_archive.py` | Commits fetch JSON, analysis JSON, and IoC txt to the `GIT_ARCHIVE_BRANCH` branch via a git worktree at `/tmp/security-info-archive`. `ioc_file_url` derives a GitHub raw URL for the committed IoC file. See [archive-branch.md](archive-branch.md). |

### `src/parsers/ioc_xlsx.py`

Parses xlsx attachments embedded in TWCERT detail responses (`infoFile`) as base64 data URIs. `parse_xlsx_iocs` returns `(ips, hashes, domains)` tuples. `write_ioc_txt` writes a structured plain-text file to `/tmp/ioc_{intel_id}.txt`.

### `src/notifiers/`

| File | Role |
|:--|:--|
| `email.py` | SMTP sender over STARTTLS. `send_risk_digest(month, records, sheet_url, dry_run)` sends the monthly risk-team digest; `send_internal_announcement(records, dry_run)` emails RD managers for Stage 4b. In dry-run mode no email is sent; rendered HTML is written to `src/data/`. On send failure, calls `send_ops_alert` and re-raises (Stage 4b does **not** stamp 通知時間 unless the send succeeded). |
| `templates.py` | Jinja2 HTML renderers. `render_risk_digest(month, records, sheet_url)` produces the monthly digest table; `render_internal_cards(records)` produces summary cards for `核可發佈` items. |

**Sheet column notes for Stage 4b:**
- Column N「狀態」dropdown now includes the value `核可發佈` (in addition to `待審查`, `已關閉`, etc.). Stage 4b's `select_publishable` query filters on this value combined with a blank column S.
- Column S「通知時間」is stamped with the send timestamp after a successful `send_internal_announcement` call. Its presence (non-blank) doubles as the idempotency guard — already-notified rows are excluded from future runs.

### `src/utils/`

- `logging.py` — structured `log` singleton used throughout.
- `errors.py` — `TwcertLoginError`, `GeminiQuotaExhausted`, `send_ops_alert` (log-only). See [error-handling.md](error-handling.md).

## Cross-cutting rules

### Multi-CVE handling

Gemini analysis is performed **once per `IntelItem`**, regardless of how many CVEs it contains. At Stage 3, `main.py:stage_write_sheet` produces **one `SheetRow` per item**. Column G (`cve_id`) contains all CVE IDs joined by newline characters (`\n`), rendered as multiple lines in a single cell thanks to the worksheet's `wrapStrategy: WRAP` setting applied by `_format_worksheet` in `src/sinks/sheets.py`.

### Monthly dedup scope

`get_existing_intel_ids` is called with the set of `YYYY-MM` months covered by the current batch. It reads column B of each matching worksheet and returns all existing `intel_id` values. An item is skipped if its `intel_id` already appears in any of those tabs.

### Fixture mode

`USE_FIXTURE_DATA=true` (the default) makes `sheets.py` load asset context from `tests/fixtures/sample_assets.json` instead of the live Google Sheet. CISA KEV fixture data lives in `tests/fixtures/sample_cisa_kev.json`. This allows full local development without Google credentials.

### Two-source timezone contract

- **TWCERT**: `--since` is interpreted as TW+8 midnight. Workflows pass `TZ=Asia/Taipei date +%Y-%m-%d`.
- **CISA KEV**: `--since` is compared against `dateAdded` (UTC dates). Workflows pass `date -u +%Y-%m-%d`.
