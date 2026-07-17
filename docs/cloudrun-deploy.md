# Cloud Run Jobs 部署指引

把 pipeline 跑在 GCP **kdan-it-playground** 的 Cloud Run Jobs,每天由 Cloud Scheduler 觸發。取代 GitHub Actions 排程(見 `deployment.md`,排程已移除,僅留手動 `workflow_dispatch`)。

## 0. 變數

```bash
export PROJECT_ID=kdan-it-playground
export PROJECT_NUMBER=962438265955
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
git branch -D data 2>/dev/null   # 見下方警告:本機 data 分支會被烤進映像
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
```

> ⚠️ **必加 `--platform linux/amd64`**:Cloud Run 只跑 amd64,若在 Apple Silicon(arm64)build 而未指定平台,容器會以「Application failed to start / exec format error」啟動失敗。
>
> ⚠️ **build 前務必刪掉本機 `data` 分支**:映像 `COPY . /app` 且刻意保留 `.git`,故本機若有 `data` 分支會**連同它當時的位置一起烤進映像**。`_ensure_worktree` 在本機分支已存在時**不會 fetch**,容器於是永遠工作在那個凍結的快照上。歸檔本身看不出異狀(append-only + push 時 rebase),但**任何需要讀回狀態的功能會直接失效**——TWCERT staleness 告警會每天判定「第一次執行」而永遠不發信。`origin/data` 保有完整歷史,本機分支沒有保留價值。詳見 `archive-branch.md`。
>
> **本機無 `docker buildx` 時,改用 Cloud Build(推薦)**:`gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" .` —— 在 Google amd64 機器原生 build,免平台問題。本 repo 已附 `.gcloudignore`(保留 `.git`,故映像含 git 歷史、歸檔可運作);需先啟用 `cloudbuild.googleapis.com`。

## 4. Secrets(Secret Manager)

```bash
printf %s "$GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=- --project "$PROJECT_ID"
printf %s "$TWCERT_ACCOUNT"  | gcloud secrets create TWCERT_ACCOUNT  --data-file=- --project "$PROJECT_ID"
printf %s "$TWCERT_PASSWORD" | gcloud secrets create TWCERT_PASSWORD --data-file=- --project "$PROJECT_ID"
printf %s "$GITHUB_PAT"      | gcloud secrets create GITHUB_PAT      --data-file=- --project "$PROJECT_ID"
printf %s "$SMTP_PASSWORD"   | gcloud secrets create SMTP_PASSWORD   --data-file=- --project "$PROJECT_ID"
```

- `GEMINI_API_KEY`:AI Studio 免費 key。
- `GITHUB_PAT`:fine-grained PAT,限 repo `kdan-mobile-software-ltd/security_info_bot`,**Contents: Read and write**(用於 push `data` 分支)。
- `SMTP_PASSWORD`:寄件帳號的 App Password(email 發佈層用)。

## 5. Runtime SA + 授權讀取 secrets

```bash
gcloud iam service-accounts create intel-bot --project "$PROJECT_ID"
for S in GEMINI_API_KEY TWCERT_ACCOUNT TWCERT_PASSWORD GITHUB_PAT SMTP_PASSWORD; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:$RUNTIME_SA" \
    --role=roles/secretmanager.secretAccessor --project "$PROJECT_ID"
done
```

> **Sheets 認證用 ADC**(直接用此 runtime SA `intel-bot` 身分,無需 JSON 金鑰)。把此 SA email 加進**情資 Sheet(`威脅情資管理列表`)與資產 Sheet** 的「共用」為編輯者;並確認專案已啟用 **Google Sheets API + Drive API**(`gcloud services enable sheets.googleapis.com drive.googleapis.com --project "$PROJECT_ID"`)。本機開發若要寫真 Sheet,可設 `GOOGLE_SA_JSON_FILE` 指向金鑰檔,或 `gcloud auth application-default login`。

## 6. 建立兩個 Cloud Run Jobs

共用 env(把 `<...>` 換成實際 Sheet ID):

```bash
COMMON_ENV="GEMINI_MODEL=gemini-3.5-flash,GOOGLE_SHEET_ID=<SHEET_ID>,POOL_WORKSHEET=2026_威脅情資表,ASSETS_SHEET_ID=<ASSETS_ID>,ASSETS_WORKSHEET=工作表1,GIT_ARCHIVE_BRANCH=data,GIT_ARCHIVE_AUTO_PUSH=true,USE_FIXTURE_DATA=false"
```

CISA(不需 TWCERT secrets):

```bash
gcloud run jobs create intel-cisa \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 900 --memory 512Mi \
  --set-env-vars "INTEL_SOURCE=cisa_kev,$COMMON_ENV" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,GITHUB_PAT=GITHUB_PAT:latest"
```

TWCERT(加 TWCERT secrets;`SMTP_*` / `OPS_ALERT_EMAILS` 供 staleness 告警寄信):

```bash
gcloud run jobs create intel-twcert \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 900 --memory 512Mi \
  --set-env-vars "INTEL_SOURCE=twcert,SMTP_USER=<寄件帳號>,OPS_ALERT_EMAILS=<收件人>,$COMMON_ENV" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,GITHUB_PAT=GITHUB_PAT:latest,TWCERT_ACCOUNT=TWCERT_ACCOUNT:latest,TWCERT_PASSWORD=TWCERT_PASSWORD:latest,SMTP_PASSWORD=SMTP_PASSWORD:latest"
```

> ⚠️ **`SMTP_PASSWORD` 與 `OPS_ALERT_EMAILS` 缺一,staleness 告警就靜默失效**:`_smtp_send` 只會記一行 `No recipients configured` 並回傳 False,不會拋錯。此 job 是唯一會寄 ops 告警的 job,故 SMTP 設定必須掛在這裡(step 4 建立的 `SMTP_PASSWORD` secret 若只建不掛,等於沒有)。既有 job 補設定:
>
> ```bash
> gcloud run jobs update intel-twcert --region "$REGION" --project "$PROJECT_ID" \
>   --update-env-vars "SMTP_USER=<寄件帳號>,OPS_ALERT_EMAILS=<收件人>" \
>   --update-secrets "SMTP_PASSWORD=SMTP_PASSWORD:latest"
> ```
>
> 告警門檻預設連續 7 天無新情資,以 `TWCERT_STALE_DAYS` 調整(見 `configuration.md`)。實測 TWCERT 最長合法安靜期正好是 7 天,故預設值會在合法安靜期當天觸發一次;要更保守可設 `TWCERT_STALE_DAYS=9`。

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

# cisa 09:00、twcert 09:05 —— 兩者都 push 到 data 分支,錯開 5 分鐘避免
# 同時觸發時 twcert 的 `git rebase origin/data` 撞上 cisa 剛前進的遠端而衝突(exit 128)。
for PAIR in "intel-cisa:0 9 * * *" "intel-twcert:5 9 * * *"; do
  JOB="${PAIR%%:*}"; SCHED="${PAIR#*:}"
  gcloud scheduler jobs create http "$JOB-daily" \
    --location "$REGION" --project "$PROJECT_ID" \
    --schedule="$SCHED" --time-zone="Asia/Taipei" \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_NUMBER/jobs/$JOB:run" \
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

## 10. Email 發佈層 Jobs(月信 / 內部發佈)

email 兩個模式(`--notify-risk`、`--publish-internal`)已在同一映像內,但**不能用預設 entrypoint**(`docker-entrypoint.sh` 固定跑 `--source ... --since ...` 的擷取流程,且強制 `INTEL_SOURCE`);因此這兩個 Job 用 `--command/--args` 覆寫 entrypoint,直接跑 `uv run python main.py <mode>`。前置:完成 §4 的 `SMTP_PASSWORD` secret 與 §5 的授權。

共用 email env(把 `<...>` 換成實際值;收件人逗號分隔):

```bash
EMAIL_ENV="GOOGLE_SHEET_ID=<SHEET_ID>|USE_FIXTURE_DATA=false|SMTP_HOST=smtp.gmail.com|SMTP_PORT=587|SMTP_USER=<secbot@example.com>|EMAIL_FROM=<secbot@example.com>"
```

> `^|^` 前綴告訴 gcloud 使用 `|` 作為 key=value 對的分隔符,這樣收件人清單內的逗號才不會被誤解析。

風險小組月信(`--notify-risk`):

```bash
gcloud run jobs create intel-notify-risk \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 600 --memory 512Mi \
  --command uv --args run,python,main.py,--notify-risk \
  --set-env-vars "^|^$EMAIL_ENV|RISK_TEAM_EMAILS=a@co,b@co" \
  --set-secrets "SMTP_PASSWORD=SMTP_PASSWORD:latest"
```

內部發佈(`--publish-internal`):

```bash
gcloud run jobs create intel-publish-internal \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 600 --memory 512Mi \
  --command uv --args run,python,main.py,--publish-internal \
  --set-env-vars "^|^$EMAIL_ENV|INTERNAL_ANNOUNCE_EMAILS=rd-a@co,rd-b@co" \
  --set-secrets "SMTP_PASSWORD=SMTP_PASSWORD:latest"
```

排程(run.invoker + Scheduler;月信每月 1 號 09:00、內部發佈平日每天 10:00 TW+8):

```bash
for JOB in intel-notify-risk intel-publish-internal; do
  gcloud run jobs add-iam-policy-binding "$JOB" \
    --member="serviceAccount:$TRIGGER_SA" --role=roles/run.invoker \
    --region "$REGION" --project "$PROJECT_ID"
done

gcloud scheduler jobs create http intel-notify-risk-monthly \
  --location "$REGION" --project "$PROJECT_ID" \
  --schedule="0 9 1 * *" --time-zone="Asia/Taipei" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_NUMBER/jobs/intel-notify-risk:run" \
  --http-method=POST --oauth-service-account-email="$TRIGGER_SA"

gcloud scheduler jobs create http intel-publish-internal-daily \
  --location "$REGION" --project "$PROJECT_ID" \
  --schedule="0 10 * * 1-5" --time-zone="Asia/Taipei" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_NUMBER/jobs/intel-publish-internal:run" \
  --http-method=POST --oauth-service-account-email="$TRIGGER_SA"
```

> notify-risk / publish-internal 不需 Gemini 或 GitHub PAT(只讀寫 Sheet + 寄信)。月信預設當月;要指定月份,執行時覆寫 args:`--args run,python,main.py,--notify-risk,--month,<YYYY-MM>`。

## 注意事項

- `GEMINI_MODEL` 必為 `gemini-3.5-flash`(免費層僅 Flash)。
- `GITHUB_PAT` 有到期日,到期需 `gcloud secrets versions add GITHUB_PAT --data-file=-` 更新。
- 私有 repo 的 IoC raw 連結需登入才開得了(與原 GitHub Actions 行為相同)。
- `/tmp` 是記憶體 tmpfs;量大時調高 `--memory`。
- 容器預設 `--since` 為「昨天」(twcert 以 TW+8、cisa_kev 以 UTC 計);與本機手動 `uv run python main.py`(預設今天)不同,月度去重會吸收一天的重疊。
- 排程由原 GitHub Actions 的 4 次/天改為每天 1 次(cisa `0 9 * * *`、twcert `5 9 * * *` TW+8);CISA KEV 的更新偵測頻率因此降低,屬刻意取捨。
- 兩個 Job 都 push 到 `data` 分支,故排程**刻意錯開 5 分鐘**:同時在 09:00 觸發時,較晚 push 的 twcert 會因 `git rebase origin/data` 撞上 cisa 剛前進的遠端而以 exit 128 失敗(2026-07-02 曾發生)。若之後新增其他也寫 `data` 分支的 Job,同樣需錯開觸發時間。
