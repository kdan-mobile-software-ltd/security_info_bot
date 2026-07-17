# Configuration

All settings are env vars loaded at startup via `python-dotenv` (`src/config.py`). Copy `.env.example` as the canonical starting point.

## Environment variables

| Variable | Purpose | Default | Required when |
|:--|:--|:--|:--|
| `TWCERT_ACCOUNT` | TWCERT enterprise portal username | — | `--source twcert` |
| `TWCERT_PASSWORD` | TWCERT enterprise portal password | — | `--source twcert` |
| `GEMINI_API_KEY` | Google Gemini API key | — | Stage 2 (analyze) |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-pro-preview` | No |
| `GOOGLE_SA_JSON_FILE` | Path to Service Account JSON file | — | Stage 2/3 (Google APIs) |
| `GOOGLE_SA_JSON_B64` | Base64-encoded Service Account JSON | — | Stage 2/3 (alternative) |
| `GOOGLE_SHEET_ID` | Intel Google Sheet ID | — | Stage 3 (write sheet) |
| `ASSETS_SHEET_ID` | Asset inventory Google Sheet ID | — | Stage 2 (assets context) |
| `ASSETS_WORKSHEET` | Asset sheet worksheet name | `工作表1` | No |
| `GIT_ARCHIVE_BRANCH` | Branch name for artefact archive | `""` (disabled) | No |
| `GIT_ARCHIVE_AUTO_PUSH` | Push archive branch after each commit | `false` | No (set `true` in CI) |
| `USE_FIXTURE_DATA` | Load assets/CISA KEV from `tests/fixtures/` | `true` | No |

## Email publishing env vars (Stage 4a / 4b)

Stage 4a (`--notify-risk`, monthly risk-team digest) and Stage 4b (`--publish-internal`, internal RD-manager announcements) are delivered via SMTP. The following env vars configure the transport and recipient lists.

| Variable | Purpose | Default | Required when |
|:--|:--|:--|:--|
| `SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` | Stage 4a/4b (email) |
| `SMTP_PORT` | SMTP port (STARTTLS) | `587` | Stage 4a/4b (email) |
| `SMTP_USER` | SMTP authentication username | — | Stage 4a/4b (email) |
| `SMTP_PASSWORD` | SMTP authentication password / app password | — | Stage 4a/4b (email) |
| `EMAIL_FROM` | `From:` header (display name + address) | — | Stage 4a/4b (email) |
| `RISK_TEAM_EMAILS` | Comma-separated recipient list for the monthly risk-team digest | — | Stage 4a (`--notify-risk`) |
| `INTERNAL_ANNOUNCE_EMAILS` | Comma-separated recipient list for internal RD-manager announcements | — | Stage 4b (`--publish-internal`) |
| `OPS_ALERT_EMAILS` | Comma-separated recipient list for ops alerts (TWCERT staleness) | — | TWCERT staleness alert |

Notes:
- The default transport is SMTP with STARTTLS (`smtp.gmail.com:587`). Use a Google Workspace app password or a third-party relay as needed.
- `RISK_TEAM_EMAILS` and `INTERNAL_ANNOUNCE_EMAILS` accept multiple addresses separated by commas (no spaces required).
- In **fixture mode** (`USE_FIXTURE_DATA=true`), email is **not sent**. Instead, the rendered HTML is written to `src/data/email_preview_<stage>_<ts>.html` for local review.

## TWCERT staleness alert

TWCERT routinely publishes nothing for days (the longest observed healthy quiet stretch is 7 days), so a broken fetcher and a genuinely quiet TWCERT look identical in the logs. Stage 1 therefore records the server's reported intel total after every TWCERT fetch and alerts when it stops moving.

| Variable | Purpose | Default | Required when |
|:--|:--|:--|:--|
| `TWCERT_STALE_DAYS` | Consecutive days with an unchanged server total before alerting | `7` | TWCERT staleness alert |

- State lives on the archive branch at `twcert/_fetch_state.json` (`last_total` / `last_changed` / `alerted`); the container is stateless, so the branch is the only thing that survives between daily runs. With `GIT_ARCHIVE_BRANCH` unset the check cannot persist state and never alerts.
- Each quiet stretch alerts **once**. The flag is only recorded after the mail is actually delivered, so a failed send retries on the next run.
- Delivery is email via `OPS_ALERT_EMAILS`, plus the existing `[OPS]` `log.error` line. **With `OPS_ALERT_EMAILS` unset nothing is delivered** — `_smtp_send` logs `No recipients configured` and returns False. The `[OPS]` log line alone reaches no one unless a log-based alert policy exists in GCP.
- `--dry-run` renders a preview instead of sending and never writes state.
- The check never raises: any failure is logged as a warning and the pipeline continues.

## Google Service Account credential resolution

`src/config.py:get_service_account_path()` resolves credentials in this order:

1. If `GOOGLE_SA_JSON_FILE` is set **and** the file exists → use it directly.
2. Else if `GOOGLE_SA_JSON_B64` is set → base64-decode into a temp file (`/tmp/sa_*.json`) and use that path.
3. Otherwise → raises `RuntimeError`.

The SA must have:
- **Sheets Editor** on the intel Google Sheet (`GOOGLE_SHEET_ID`).
- **Sheets Viewer** on the asset inventory sheet (`ASSETS_SHEET_ID`).

## Fixture mode

When `USE_FIXTURE_DATA=true` (the default), `src/sinks/sheets.py:load_assets_context()` reads from `tests/fixtures/sample_assets.json` instead of the live Google Sheet. This allows local development and CI unit tests to run without any Google credentials.

Fixture files:

| File | Replaces |
|:--|:--|
| `tests/fixtures/sample_assets.json` | Live asset inventory worksheet |
| `tests/fixtures/sample_cisa_kev.json` | Live CISA KEV JSON feed |

`tests/fixtures/sample_twcert_iocs.xlsx` is used by IoC parser unit tests and has no runtime fixture-mode equivalent (TWCERT fetcher requires live credentials either way).

## `GIT_ARCHIVE_BRANCH` behaviour

- **Empty string (default)**: All `commit_files` / `ioc_file_url` calls are silent no-ops. No worktree is created. No archive branch is needed.
- **Set to a branch name** (e.g., `data`): Worktree is created at `/tmp/security-info-archive` on first use; branch is auto-created if it does not exist.
- **`GIT_ARCHIVE_AUTO_PUSH=true`**: Each `commit_files` call immediately pushes the branch to `origin`. Set this in CI; leave it `false` locally unless you want to push after every pipeline run.
