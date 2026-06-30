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
