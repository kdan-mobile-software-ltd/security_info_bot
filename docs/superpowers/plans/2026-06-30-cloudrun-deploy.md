# Cloud Run Jobs Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the existing pipeline and run it on Cloud Run Jobs + Cloud Scheduler in `kdan-it-playground`, replacing the GitHub Actions schedules — with zero application code changes.

**Architecture:** A Docker image (python3.11 + uv + git) containing the repo (including `.git`) runs `main.py` to completion. Git auth for the archive `data` branch is injected via a credential helper reading `$GITHUB_PAT` (origin normalized to HTTPS so the IoC raw URL still resolves). Two Cloud Run Jobs (one per source) are triggered daily by Cloud Scheduler. The GitHub workflows keep only their manual `workflow_dispatch` trigger.

**Tech Stack:** Docker, uv, GNU coreutils (date/tzdata), Google Cloud (Artifact Registry, Cloud Run Jobs, Cloud Scheduler, Secret Manager, IAM), GitHub Actions YAML.

## Global Constraints

- GCP project: `kdan-it-playground` (number `962438265955`); region `asia-east1`.
- Gemini model MUST be `gemini-3.5-flash` (only Flash is in the free tier; Pro would bill or be rejected).
- Google Sheets auth stays on `GOOGLE_SA_JSON_B64` — do NOT switch to ADC, do NOT modify `src/`.
- Archive push uses a GitHub PAT injected via `git config credential.helper` reading `$GITHUB_PAT`. The PAT MUST NOT appear in the remote URL. `origin` must be the clean HTTPS form `https://github.com/kdan-mobile-software-ltd/security_info_bot.git` so `git_archive.py::_github_base()` resolves the IoC raw URL.
- The image MUST contain `.git` (the `data`-branch worktree mechanics and origin parsing depend on it) and MUST have `git` and `tzdata` installed (TW+8 `--since` computation needs tzdata).
- No `src/` application code changes anywhere in this plan.
- Schedule: once daily, `0 9 * * *` with `--time-zone=Asia/Taipei`.

---

### Task 1: Container image (Dockerfile + entrypoint + .dockerignore)

**Files:**
- Create: `Dockerfile`
- Create: `docker-entrypoint.sh`
- Create: `.dockerignore`

**Interfaces:**
- Produces: a runnable image whose `ENTRYPOINT` is `docker-entrypoint.sh`. The entrypoint reads env `INTEL_SOURCE` (`twcert`|`cisa_kev`), optional `SINCE` (`YYYY-MM-DD`), and forwards any extra args to `main.py`. Consumed by Task 3 (Cloud Run Jobs set `INTEL_SOURCE` and secrets).

- [ ] **Step 1: Write `.dockerignore`**

Create `.dockerignore` (keeps `.git`, drops local cruft so the build context is clean):

```
.venv/
src/data/
**/__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.env
docs/superpowers/
```

- [ ] **Step 2: Write `docker-entrypoint.sh`**

Create `docker-entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SOURCE="${INTEL_SOURCE:?INTEL_SOURCE must be set to twcert or cisa_kev}"

if [ -z "${SINCE:-}" ]; then
  if [ "$SOURCE" = "twcert" ]; then
    SINCE="$(TZ=Asia/Taipei date -d yesterday +%F)"
  else
    SINCE="$(date -u -d yesterday +%F)"
  fi
fi

exec uv run python main.py --source "$SOURCE" --since "$SINCE" "$@"
```

- [ ] **Step 3: Write `Dockerfile`**

Create `Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN uv sync --frozen --no-dev

RUN git remote set-url origin https://github.com/kdan-mobile-software-ltd/security_info_bot.git \
    && git config --global --add safe.directory /app \
    && git config --global credential.helper \
       '!f() { echo username=x-access-token; echo "password=${GITHUB_PAT}"; }; f' \
    && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
```

- [ ] **Step 4: Build the image**

Run: `docker build -t intel-bot:test .`
Expected: build completes with `naming to docker.io/library/intel-bot:test` (or equivalent success line). Requires a working Docker daemon.

- [ ] **Step 5: Smoke-run with zero credentials**

Run:
```bash
docker run --rm \
  -e USE_FIXTURE_DATA=true \
  -e INTEL_SOURCE=cisa_kev \
  -e SINCE=2024-01-01 \
  intel-bot:test --fetch-only --limit 3
```
Expected: logs show `=== CISA_KEV 情資擷取開始 ===`, fetches CISA KEV items, `Limiting to 3 items`, saves a JSON, and exits 0. No credential errors (CISA feed is public; `GIT_ARCHIVE_BRANCH` unset → archive is a no-op).

- [ ] **Step 6: Verify the entrypoint requires INTEL_SOURCE**

Run: `docker run --rm intel-bot:test; echo "exit=$?"`
Expected: fails fast with `INTEL_SOURCE must be set to twcert or cisa_kev` and a non-zero exit.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-entrypoint.sh .dockerignore
git commit -m "feat(docker): container image + entrypoint for Cloud Run Jobs"
```

---

### Task 2: Remove GitHub Actions schedules

**Files:**
- Modify: `.github/workflows/twcert.yml` (the `on:` block)
- Modify: `.github/workflows/cisa_kev.yml` (the `on:` block)

**Interfaces:** none (CI config). After this task neither workflow fires on a schedule; both still run via manual `workflow_dispatch`.

- [ ] **Step 1: Edit twcert.yml `on:` block**

In `.github/workflows/twcert.yml`, replace:

```yaml
on:
  schedule:
    - cron: '17 1,5,9,13 * * *'  # 09:00 TW+8
  workflow_dispatch:
    inputs:
      since:
        description: 'Fetch start date (YYYY-MM-DD, TW+8). Defaults to yesterday.'
        required: false
        default: ''
```

with:

```yaml
on:
  workflow_dispatch:
    inputs:
      since:
        description: 'Fetch start date (YYYY-MM-DD, TW+8). Defaults to yesterday.'
        required: false
        default: ''
```

- [ ] **Step 2: Edit cisa_kev.yml `on:` block**

In `.github/workflows/cisa_kev.yml`, replace:

```yaml
on:
  schedule:
    - cron: '17 1,5,9,13 * * *'  # 09:17, 13:17, 17:17, 21:17 TW+8
  workflow_dispatch:
    inputs:
      since:
        description: 'Fetch start date (YYYY-MM-DD, UTC). Defaults to yesterday.'
        required: false
        default: ''
```

with:

```yaml
on:
  workflow_dispatch:
    inputs:
      since:
        description: 'Fetch start date (YYYY-MM-DD, UTC). Defaults to yesterday.'
        required: false
        default: ''
```

- [ ] **Step 3: Verify no schedule remains and YAML still parses**

Run: `grep -rn "schedule" .github/workflows/twcert.yml .github/workflows/cisa_kev.yml; echo "matches=$?"`
Expected: no output and `matches=1` (grep found nothing).

Run: `uv run python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/twcert.yml','.github/workflows/cisa_kev.yml']]; print('ok')"`
Expected: `ok`. (If PyYAML is unavailable, instead confirm by inspection that each file's `on:` contains only `workflow_dispatch`.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/twcert.yml .github/workflows/cisa_kev.yml
git commit -m "ci: drop schedule triggers (moved to Cloud Run); keep manual dispatch"
```

---

### Task 3: Deployment guide (docs/cloudrun-deploy.md)

**Files:**
- Create: `docs/cloudrun-deploy.md`
- Modify: `CLAUDE.md` / `AGENTS.md` documentation index (add a link to the new guide)

**Interfaces:** none (documentation). Consumes the image from Task 1 and references the schedule-removal from Task 2.

- [ ] **Step 1: Write the deploy guide**

Create `docs/cloudrun-deploy.md` with exactly this content:

````markdown
# Cloud Run Jobs 部署指引

把 pipeline 跑在 GCP **kdan-it-playground** 的 Cloud Run Jobs,每天由 Cloud Scheduler 觸發。取代 GitHub Actions 排程(見 `deployment.md`,排程已移除,僅留手動 `workflow_dispatch`)。

## 0. 變數

```bash
export PROJECT_ID=kdan-it-playground
export REGION=asia-east1
export REPO=security-info-bot
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/intel:latest
export RUNTIME_SA=intel-bot@$PROJECT_ID.iam.gserviceaccount.com
export TRIGGER_SA=intel-scheduler@$PROJECT_ID.iam.gserviceaccount.com
```

## 1. 啟用 API

```bash
gcloud services enable \
  run.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT_ID"
```

## 2. Artifact Registry

```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" --project "$PROJECT_ID"
```

## 3. Build & Push 映像

本機 Docker(可控制 build context、確保含 `.git`):

```bash
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

> 用 Cloud Build(`gcloud builds submit --tag $IMAGE`)亦可,但需新增 `.gcloudignore` 並確保**不要**排除 `.git`,否則映像內無 git 歷史、歸檔會失敗。

## 4. Secrets(Secret Manager)

```bash
printf %s "$GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=- --project "$PROJECT_ID"
base64 -i service_account.json | gcloud secrets create GOOGLE_SA_JSON_B64 --data-file=- --project "$PROJECT_ID"
printf %s "$TWCERT_ACCOUNT"  | gcloud secrets create TWCERT_ACCOUNT  --data-file=- --project "$PROJECT_ID"
printf %s "$TWCERT_PASSWORD" | gcloud secrets create TWCERT_PASSWORD --data-file=- --project "$PROJECT_ID"
printf %s "$GITHUB_PAT"      | gcloud secrets create GITHUB_PAT      --data-file=- --project "$PROJECT_ID"
```

- `GEMINI_API_KEY`:AI Studio 免費 key。
- `GOOGLE_SA_JSON_B64`:Service Account JSON 的 base64。
- `GITHUB_PAT`:fine-grained PAT,限 repo `kdan-mobile-software-ltd/security_info_bot`,**Contents: Read and write**(用於 push `data` 分支)。

## 5. Runtime SA + 授權讀取 secrets

```bash
gcloud iam service-accounts create intel-bot --project "$PROJECT_ID"
for S in GEMINI_API_KEY GOOGLE_SA_JSON_B64 TWCERT_ACCOUNT TWCERT_PASSWORD GITHUB_PAT; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:$RUNTIME_SA" \
    --role=roles/secretmanager.secretAccessor --project "$PROJECT_ID"
done
```

> 另外把這個 SA 的 email 在目標 Google Sheet 與資產 Sheet 按「共用」加為編輯者(Sheets 認證仍走 `GOOGLE_SA_JSON_B64`,須與此 SA 對應)。

## 6. 建立兩個 Cloud Run Jobs

共用 env(把 `<...>` 換成實際 Sheet ID):

```bash
COMMON_ENV="GEMINI_MODEL=gemini-3.5-flash,GOOGLE_SHEET_ID=<SHEET_ID>,ASSETS_SHEET_ID=<ASSETS_ID>,ASSETS_WORKSHEET=工作表1,GIT_ARCHIVE_BRANCH=data,GIT_ARCHIVE_AUTO_PUSH=true,USE_FIXTURE_DATA=false"
```

CISA(不需 TWCERT secrets):

```bash
gcloud run jobs create intel-cisa \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 900 --memory 512Mi \
  --set-env-vars "INTEL_SOURCE=cisa_kev,$COMMON_ENV" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,GOOGLE_SA_JSON_B64=GOOGLE_SA_JSON_B64:latest,GITHUB_PAT=GITHUB_PAT:latest"
```

TWCERT(加 TWCERT secrets):

```bash
gcloud run jobs create intel-twcert \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 900 --memory 512Mi \
  --set-env-vars "INTEL_SOURCE=twcert,$COMMON_ENV" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,GOOGLE_SA_JSON_B64=GOOGLE_SA_JSON_B64:latest,GITHUB_PAT=GITHUB_PAT:latest,TWCERT_ACCOUNT=TWCERT_ACCOUNT:latest,TWCERT_PASSWORD=TWCERT_PASSWORD:latest"
```

## 7. 手動驗證

```bash
gcloud run jobs execute intel-cisa --region "$REGION" --project "$PROJECT_ID" --wait
```

檢查:Google Sheet 當月分頁有新列;`git fetch origin data && git log origin/data` 有新 commit。
手動覆寫日期:加 `--update-env-vars SINCE=2026-06-01`。

## 8. 排程觸發(Cloud Scheduler)

```bash
gcloud iam service-accounts create intel-scheduler --project "$PROJECT_ID"

for JOB in intel-cisa intel-twcert; do
  gcloud run jobs add-iam-policy-binding "$JOB" \
    --member="serviceAccount:$TRIGGER_SA" --role=roles/run.invoker \
    --region "$REGION" --project "$PROJECT_ID"
done

for JOB in intel-cisa intel-twcert; do
  gcloud scheduler jobs create http "$JOB-daily" \
    --location "$REGION" --project "$PROJECT_ID" \
    --schedule="0 9 * * *" --time-zone="Asia/Taipei" \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB:run" \
    --http-method=POST \
    --oauth-service-account-email="$TRIGGER_SA"
done
```

## 9. 更新映像(日後改版)

```bash
docker build -t "$IMAGE" . && docker push "$IMAGE"
gcloud run jobs update intel-cisa   --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID"
gcloud run jobs update intel-twcert --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID"
```

## 注意事項

- `GEMINI_MODEL` 必為 `gemini-3.5-flash`(免費層僅 Flash)。
- `GITHUB_PAT` 有到期日,到期需 `gcloud secrets versions add GITHUB_PAT --data-file=-` 更新。
- 私有 repo 的 IoC raw 連結需登入才開得了(與原 GitHub Actions 行為相同)。
- `/tmp` 是記憶體 tmpfs;量大時調高 `--memory`。
````

- [ ] **Step 2: Add the guide to the docs index**

In `CLAUDE.md` (and its symlink target `AGENTS.md`), add one bullet under "Documentation Index":

```markdown
- [Cloud Run Deploy](docs/cloudrun-deploy.md) — 在 kdan-it-playground 以 Cloud Run Jobs + Cloud Scheduler 部署(取代 GitHub Actions 排程)
```

- [ ] **Step 3: Verify links and project/region consistency**

Run: `grep -n "kdan-it-playground\|asia-east1\|gemini-3.5-flash\|credential.helper\|Contents: Read and write" docs/cloudrun-deploy.md`
Expected: matches present for project id, region, the Flash model, the credential-helper note, and the PAT scope — confirming the guide matches the spec's Global Constraints.

Run: `grep -n "cloudrun-deploy" CLAUDE.md`
Expected: the new index bullet appears.

- [ ] **Step 4: Commit**

```bash
git add docs/cloudrun-deploy.md CLAUDE.md AGENTS.md
git commit -m "docs(cloudrun): deployment guide + docs index link"
```

---

## Self-Review

**Spec coverage:**
- §3/§6 container image (uv+git+tzdata, COPY incl .git, origin→HTTPS, credential helper, entrypoint) → Task 1. ✓
- §3/§6 PAT via credential helper, not in URL → Task 1 Dockerfile + Global Constraints. ✓
- §3 model = gemini-3.5-flash → Task 3 env + Global Constraints. ✓
- §5/§7 two Cloud Run Jobs + two Schedulers, asia-east1, `0 9 * * *` Asia/Taipei → Task 3 §6/§8. ✓
- §8 Secrets + runtime SA secretAccessor + trigger SA run.invoker → Task 3 §4/§5/§8. ✓
- §9 remove GitHub Actions schedules, keep workflow_dispatch → Task 2. ✓
- §11 smoke test (fixture, cisa fetch-only, zero creds) → Task 1 Step 5. ✓
- §2 no src/ changes → no task touches `src/`. ✓

**Placeholder scan:** `<SHEET_ID>` / `<ASSETS_ID>` in Task 3 are explicit user-substituted deployment values (documented as such), not plan placeholders; every step has concrete content. No TBD/TODO. ✓

**Type/identifier consistency:** Job names `intel-cisa` / `intel-twcert`, SAs `intel-bot@` / `intel-scheduler@`, `INTEL_SOURCE` values `cisa_kev`/`twcert`, image var `$IMAGE`, and the HTTPS origin string are used identically across Tasks 1 and 3. The entrypoint's `INTEL_SOURCE`/`SINCE` contract (Task 1) matches the env Cloud Run Jobs set (Task 3). ✓
