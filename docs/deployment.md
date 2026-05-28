# Deployment

> **首次部署？** 請先看 [deployment-guide.md](deployment-guide.md)（SA 建立、API 啟用、Sheet 分享、GitHub Secrets 設定）。本文件記錄 CI 內部行為，假設所有憑證已就位。

## GitHub Actions workflows

Two independent workflows under `.github/workflows/`:

| Workflow | File | Source |
|:--|:--|:--|
| TWCERT 情資分析 | `twcert.yml` | `--source twcert` |
| CISA KEV 情資分析 | `cisa_kev.yml` | `--source cisa_kev` |

Both trigger on:
- **`schedule`**: daily at `0 1 * * *` (01:00 UTC = 09:00 TW+8).
- **`workflow_dispatch`**: manual trigger from the GitHub Actions UI.

## Per-run command

```yaml
# twcert.yml
run: uv run python main.py --source twcert --since $(TZ=Asia/Taipei date +%Y-%m-%d)

# cisa_kev.yml
run: uv run python main.py --source cisa_kev --since $(date -u +%Y-%m-%d)
```

TWCERT uses `TZ=Asia/Taipei` so `--since` matches the TW+8 day boundary used inside the fetcher. CISA KEV uses UTC to match `dateAdded` in the CISA feed.

## Required permissions

```yaml
permissions:
  contents: write   # needed to push the archive branch
```

Checkout step uses `fetch-depth: 0` so the archive branch history is available for the worktree:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

## Environment variables in workflows

Hard-coded in the workflow `env` block:

| Variable | Value |
|:--|:--|
| `USE_FIXTURE_DATA` | `'false'` |
| `GIT_ARCHIVE_AUTO_PUSH` | `'true'` |
| `GEMINI_MODEL` | `${{ secrets.GEMINI_MODEL \|\| 'gemini-3.1-pro-preview' }}` |
| `ASSETS_WORKSHEET` | `${{ secrets.ASSETS_WORKSHEET \|\| '工作表1' }}` |
| `GIT_ARCHIVE_BRANCH` | `${{ secrets.GIT_ARCHIVE_BRANCH \|\| 'data' }}` |

## GitHub Secrets required

| Secret | Required for |
|:--|:--|
| `GEMINI_API_KEY` | Both workflows |
| `GOOGLE_SA_JSON_B64` | Both workflows |
| `GOOGLE_SHEET_ID` | Both workflows |
| `ASSETS_SHEET_ID` | Both workflows |
| `TWCERT_ACCOUNT` | TWCERT workflow only |
| `TWCERT_PASSWORD` | TWCERT workflow only |

Optional secrets (fall back to defaults if absent): `GEMINI_MODEL`, `ASSETS_WORKSHEET`, `GIT_ARCHIVE_BRANCH`.

## Self-hosted runner

If the TWCERT portal enforces IP allowlisting, change `runs-on: ubuntu-latest` to `runs-on: self-hosted` in `twcert.yml` to route through a fixed-IP runner.

## Archive branch push

`GIT_ARCHIVE_AUTO_PUSH=true` causes each `commit_files` call inside the pipeline to push immediately to `origin/{GIT_ARCHIVE_BRANCH}`. The workflow's `GITHUB_TOKEN` has `contents: write` permission and `actions/checkout@v4` configures git credentials for the session, so the push from the worktree at `/tmp/security-info-archive` authenticates correctly.

No branch-protection rules should be applied to the archive branch — the `GITHUB_TOKEN` default actor cannot bypass them.
