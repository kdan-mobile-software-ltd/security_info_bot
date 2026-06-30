# Cloud Run Jobs 部署設計（取代 GitHub Actions 排程）

- 日期：2026-06-30
- 分支：`feat/cloudrun-deploy`（從 `main` 開出）
- 狀態：設計待審

## 1. 問題陳述

現有 pipeline 靠 GitHub Actions（`twcert.yml` / `cisa_kev.yml`）排程自動執行。需求是把自動執行搬到自有 GCP 專案 **kdan-it-playground**（專案號 `962438265955`）的 **Cloud Run Jobs**，並停用 GitHub Actions 的排程以免雙跑。

核心程式（`main.py` 及各子系統）**不需修改**：它已是「跑完即結束」的 CLI，且 Gemini 走 `GEMINI_API_KEY`、Google Sheets 走 `GOOGLE_SA_JSON_B64`，皆與環境無關。本案的產出主要是**容器化 + 部署**。

## 2. 目標 / 非目標

**目標**
- 用 Cloud Run Jobs + Cloud Scheduler 取代 GitHub Actions 排程,跑 TWCERT 與 CISA KEV 兩條流程。
- 保留歸檔分支（`data`）功能,含 IoC 的 GitHub raw URL 回填到 Sheet。
- 不修改應用程式邏輯;只新增容器與部署檔案,並移除 GitHub workflow 的排程觸發。

**非目標（YAGNI）**
- 不做 Vertex AI（已選 AI Studio 免費 key）。
- 不做 VPC connector / Cloud NAT / 固定 IP（TWCERT 未鎖 IP）。
- 不改 Google Sheets 認證為 ADC（沿用 SA JSON secret）。
- 不動 email 發佈層（在另一分支 `feat/email-publishing-layer`)。

## 3. 確認的決策

| 面向 | 決定 |
|:--|:--|
| 平台 | Cloud Run **Jobs**（非 Service）+ Cloud Scheduler |
| GCP 專案 | `kdan-it-playground`（962438265955） |
| 區域 | `asia-east1` |
| Gemini | AI Studio **免費 API key**;模型固定 **`gemini-3.5-flash`**（Flash 才在免費層） |
| Google Sheets 認證 | 沿用既有 `GOOGLE_SA_JSON_B64`（不改程式） |
| 歸檔分支 | 保留;用 **GitHub PAT（HTTPS）** 推送 |
| PAT 注入方式 | **git credential helper 讀 `$GITHUB_PAT`**;origin 正規化為 HTTPS。**不可**把 PAT 塞進 remote URL（否則 `_github_base()` 解析不到、IoC 連結會壞） |
| GitHub Actions | **移除 `schedule:` 觸發**,保留 `workflow_dispatch`（手動備援） |
| TWCERT IP | 未鎖,不需固定 IP |

## 4. 整體架構

```
Cloud Scheduler (cron, asia-east1)
   ├─ job: intel-twcert  ──┐
   └─ job: intel-cisa    ──┤  POST jobs:run (OAuth, 專用 SA)
                           ▼
              Cloud Run Job (asia-east1)
                 容器 = python3.11 + uv + git + repo(含 .git)
                 （git 認證於 build 時設定）entrypoint: 算 --since → uv run python main.py
                   ├─ Gemini 分析（免費 key, gemini-3.5-flash）
                   ├─ 寫 Google Sheet（GOOGLE_SA_JSON_B64）
                   └─ push 歸檔到 data 分支（PAT, credential helper）
   Secrets: Secret Manager → Job env
```

## 5. 元件與檔案產出

| 檔案 | 說明 |
|:--|:--|
| `Dockerfile` | `ghcr.io/astral-sh/uv:python3.11-bookworm-slim` 基底 + `apt install git` + `uv sync --frozen --no-dev`;COPY 整個 repo（含 `.git`);build 時設定 git（origin→HTTPS、safe.directory、credential helper）;ENTRYPOINT = entrypoint 腳本 |
| `docker-entrypoint.sh` | 依 `INTEL_SOURCE`（twcert/cisa_kev）算 `--since`(預設昨天,TW+8 或 UTC),`exec uv run python main.py --source ... --since ... "$@"`（git 認證已於 Dockerfile build 時設定,entrypoint 不重設） |
| `.dockerignore` | 排除 `.venv`、`src/data/*`、`__pycache__`、`*.pyc`、scratch;**保留 `.git`** |
| `docs/cloudrun-deploy.md` | gcloud 操作指引（Artifact Registry、Secret Manager、Cloud Run Jobs、Cloud Scheduler、IAM）,以 `PROJECT_ID` / `REGION` 變數呈現 |
| `.github/workflows/twcert.yml` | 移除 `schedule:`,保留 `workflow_dispatch` |
| `.github/workflows/cisa_kev.yml` | 移除 `schedule:`,保留 `workflow_dispatch` |

**無任何 `src/` 應用程式碼變更。**

## 6. 容器映像設計

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN uv sync --frozen --no-dev
RUN git remote set-url origin https://github.com/kdan-mobile-software-ltd/security_info_bot.git \
    && git config --global --add safe.directory /app \
    && git config --global credential.helper \
       '!f() { echo username=x-access-token; echo "password=${GITHUB_PAT}"; }; f'
ENTRYPOINT ["/app/docker-entrypoint.sh"]
```

要點:
- **COPY 含 `.git`**:`git_archive.py` 的 `_repo_root()` / worktree 需要 repo 與 `origin`;私有 repo 用 COPY 可免 build 時認證。
- **origin 正規化 HTTPS**:讓 PAT credential helper 生效,且 `_github_base()` 解析出乾淨的 `https://github.com/kdan-mobile-software-ltd/security_info_bot` → IoC raw URL 正常。
- **credential helper 讀 `$GITHUB_PAT`**:PAT 不出現在 remote URL,執行期由 helper 提供。
- **git 已安裝**;worktree 預設 `/tmp/security-info-archive`（Cloud Run 的 `/tmp` 為記憶體 tmpfs,需留意 job 記憶體配額,設 512Mi 起）。

`docker-entrypoint.sh`（概念）:
```sh
#!/usr/bin/env bash
set -euo pipefail
SOURCE="${INTEL_SOURCE:?INTEL_SOURCE must be twcert|cisa_kev}"
if [ -z "${SINCE:-}" ]; then
  if [ "$SOURCE" = "twcert" ]; then SINCE=$(TZ=Asia/Taipei date -d yesterday +%F)
  else SINCE=$(date -u -d yesterday +%F); fi
fi
exec uv run python main.py --source "$SOURCE" --since "$SINCE" "$@"
```

## 7. Cloud Run Jobs + Cloud Scheduler

- **兩個 Job**（同一映像,差在 `INTEL_SOURCE` env）:`intel-twcert`、`intel-cisa`,region `asia-east1`,memory 512Mi、`--max-retries 1`、`--task-timeout 900s`。
- **兩個 Scheduler**（asia-east1）,各自 `POST` Cloud Run Admin API 觸發對應 Job:
  - URI:`https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/kdan-it-playground/jobs/<JOB>:run`
  - 認證:`--oauth-service-account-email`（觸發用 SA,需 `roles/run.invoker`）
  - cron:採 `--time-zone=Asia/Taipei`、`0 9 * * *`(每天 1 次,09:00 TW+8)。
- `--since` 由 entrypoint 自動計算（昨天）;手動執行可用 `gcloud run jobs execute ... --update-env-vars SINCE=YYYY-MM-DD` 覆寫。

## 8. Secrets 與 IAM

**Secret Manager（建立後授權 Job 的 runtime SA 讀取）**
| Secret | 用途 |
|:--|:--|
| `GEMINI_API_KEY` | AI Studio 免費 key（Flash） |
| `GOOGLE_SA_JSON_B64` | Google Sheets 認證 |
| `TWCERT_ACCOUNT` / `TWCERT_PASSWORD` | TWCERT 登入（僅 twcert job） |
| `GITHUB_PAT` | 歸檔 push（fine-grained、限本 repo、Contents 讀寫） |

**Job runtime SA**（例如 `intel-bot@kdan-it-playground.iam.gserviceaccount.com`）需 `roles/secretmanager.secretAccessor`。
**Scheduler 觸發 SA** 需 `roles/run.invoker`。

**Job 一般 env（非機密）**:`GOOGLE_SHEET_ID`、`ASSETS_SHEET_ID`、`ASSETS_WORKSHEET`(預設 工作表1)、`GEMINI_MODEL=gemini-3.5-flash`、`GIT_ARCHIVE_BRANCH=data`、`GIT_ARCHIVE_AUTO_PUSH=true`、`USE_FIXTURE_DATA=false`、`INTEL_SOURCE=<twcert|cisa_kev>`。

> 注意:`GOOGLE_SHEET_ID` / `ASSETS_SHEET_ID` 可視機密程度放 env 或 Secret Manager;本設計放一般 env(非密)。

## 9. 停用 GitHub Actions 排程

編輯 `twcert.yml`、`cisa_kev.yml`,移除 `on.schedule` 區塊,只保留 `workflow_dispatch`（含 `since` 輸入）作為手動備援。其餘步驟與 env 不動,確保需要時仍可在 GitHub UI 手動跑。

## 10. 錯誤處理 / 注意事項

- **`/tmp` 記憶體**:worktree 與 SA 暫存檔在 `/tmp`(tmpfs),計入 job 記憶體;512Mi 起,視量調整。
- **GEMINI_MODEL 必為 Flash**:Pro 不在免費層;誤用 Pro 會產生費用或被拒。
- **PAT 失效/權限不足**:push 會失敗 → `commit_files` 拋例外 → job 非零退出;Scheduler 會記錄失敗。PAT 用 fine-grained、設到期提醒。
- **私有 repo 的 IoC raw URL**:`https://github.com/.../raw/data/...` 需登入才開得了(與現行 GitHub Actions 行為相同,不變更)。
- **去重**:即使 Scheduler 偶發重跑,`get_existing_intel_ids` 月度去重會擋掉重複列。

## 11. 測試

- **本機 build**:`docker build -t intel-bot .` 成功。
- **本機冒煙(零憑證)**:
  ```
  docker run --rm -e USE_FIXTURE_DATA=true -e INTEL_SOURCE=cisa_kev intel-bot --fetch-only --dry-run
  ```
  預期:抓到 CISA KEV、印出項目、不寫 Sheet、不碰 git（`GIT_ARCHIVE_BRANCH` 未設→no-op）。
- **既有單元測試**:`uv run pytest tests/ -v` 仍全綠(本案不改 `src/`)。
- **部署後驗證**:`gcloud run jobs execute intel-cisa --region asia-east1` 手動跑一次,檢查 Sheet 寫入與 `data` 分支有新 commit。

## 12. Rollout 步驟（摘要,細節在 docs/cloudrun-deploy.md）

1. 建 Artifact Registry repo（asia-east1, docker）。
2. build & push 映像。
3. 建 Secrets、建 runtime SA、授 `secretAccessor`。
4. 建兩個 Cloud Run Jobs（env + secrets）。
5. 手動 `jobs execute` 驗證。
6. 建觸發 SA(`run.invoker`)+ 兩個 Cloud Scheduler。
7. 移除 GitHub Actions 排程並 push。

## 13. 風險與開放問題

- **PAT 生命週期**:fine-grained PAT 有最長到期日;到期需更新 Secret。可改用 GitHub App token,但較複雜,先用 PAT。
- **映像含 `.git`**:略增映像大小;可接受。若日後嫌大,改 build 時 shallow clone(需 build 認證)。
- **排程頻率**:每天 1 次(09:00 TW+8);要調整改 Scheduler cron 即可。
- **映像更新流程**:目前為手動 build/push;未來可加一個「push 到 main 自動 build」的 CI(本案不含)。
