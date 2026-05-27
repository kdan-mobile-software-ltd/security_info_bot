# 資安威脅情資 AI 自動化分析系統

TWCERT/CC 企業情資自動化處理系統，透過 Python + Google Gemini AI 自動擷取、分析、分級並通報資安威脅情資。

## 架構概覽

```
TWCERT 企業後台 ──(REST API)────┐
                                ├─→ 去重 → Gemini AI 分析 → Google Sheet 回填
CISA KEV JSON Feed ──(requests)─┘                          ↘ IoC .txt → git archive branch
```

- **TWCERT 爬蟲**：每日 09:00 TW+8 透過 REST API 登入企業後台，擷取當天情資；若附有 xlsx 附件則自動解析 IP / Hash / Domain IoC
- **CISA KEV 爬蟲**：每日 09:00 TW+8 抓取 CISA Known Exploited Vulnerabilities JSON Feed
- **AI 分析**：Gemini 3.1 Pro 結合公司資產清冊，產出風險分級、摘要與建議措施
- **紀錄**：分析結果回填 Google Sheet（21 欄 A–U），依月份建立 tab，支援一 CVE 一列拆分追蹤

## 環境需求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 套件管理工具

## 快速開始

```bash
# 安裝依賴
uv sync

# 設定環境變數（複製範本後填入實際值）
cp .env.example .env

# 以樣板資料模擬執行（不寫入 Sheet、不發通報，USE_FIXTURE_DATA=true 為預設）
uv run python main.py --source cisa_kev --dry-run
uv run python main.py --source twcert --dry-run

# 正式執行（需設定所有環境變數）
uv run python main.py --source twcert
uv run python main.py --source cisa_kev
```

## 指令說明

### 基本選項

| 選項 | 說明 |
|:---|:---|
| `--source {twcert,cisa_kev}` | 情資來源（必填） |
| `--since YYYY-MM-DD` | 僅擷取指定日期（含）之後的情資，**預設為今天** |
| `--limit N` | 限制最多處理 N 筆（測試用） |
| `--dry-run` | 模擬執行，不寫入 Sheet、不 commit archive |
| `--list-data [--source 前綴]` | 列出 `src/data/` 下已儲存的中間檔案 |

### 分階段執行

Pipeline 共分三個階段，可各自獨立執行與儲存中間結果：

```
Stage 1: Fetch  →  Stage 2: Analyze  →  Stage 3: Write Sheet
         ↓                  ↓
   src/data/{source}_*.json   analysis_{source}_*.json
```

#### Stage 1：僅擷取情資

```bash
# 擷取今天的情資並存至本機（不需 Gemini / Sheet 憑證）
uv run python main.py --source cisa_kev --fetch-only
uv run python main.py --source twcert --fetch-only

# 指定日期區間
uv run python main.py --source twcert --fetch-only --since 2026-05-01

# 限制筆數（測試用）
uv run python main.py --source twcert --fetch-only --limit 3
```

#### Stage 2：僅分析（從 fetch JSON 開始）

```bash
# 先列出可用的 fetch 檔案
uv run python main.py --list-data --source twcert

# 從本機 fetch JSON 執行 Gemini 分析，結果存為 analysis_*.json
uv run python main.py --source twcert \
  --load-data src/data/twcert_20260521_090000.json \
  --analyze-only

# 加 --dry-run 可略過 Sheet 去重讀取（純分析）
uv run python main.py --source twcert \
  --load-data src/data/twcert_20260521_090000.json \
  --analyze-only --dry-run --limit 2
```

#### Stage 3：僅寫入 Sheet（從 analysis JSON 開始）

```bash
uv run python main.py --list-data --source analysis_twcert

# 加 --dry-run 可預覽將寫入的列，不實際寫 Sheet / 上傳 Drive
uv run python main.py --source twcert \
  --load-analysis src/data/analysis_twcert_20260521_090000.json --dry-run

uv run python main.py --source twcert \
  --load-analysis src/data/analysis_twcert_20260521_090000.json
```

#### 從中途重跑（略過 Stage 1）

```bash
# 從已存的 fetch JSON 開始跑完整流程（Stage 2 → 3）
uv run python main.py --source twcert \
  --load-data src/data/twcert_20260521_090000.json

# 從 analysis JSON 跑 Stage 3
uv run python main.py --source twcert \
  --load-analysis src/data/analysis_twcert_20260521_090000.json
```

### 中間檔案說明

所有中間檔案存於 `src/data/`，可用 `--list-data` 搭配前綴篩選：

| 前綴 | 對應階段 | 範例 |
|:---|:---|:---|
| `twcert_` / `cisa_kev_` | Stage 1 fetch 輸出 | `twcert_20260521_090000.json` |
| `analysis_twcert_` / `analysis_cisa_kev_` | Stage 2 analyze 輸出 | `analysis_twcert_20260521_090105.json` |

```bash
uv run python main.py --list-data                        # 列出全部
uv run python main.py --list-data --source twcert        # 只看 Stage 1 twcert
uv run python main.py --list-data --source analysis_twcert  # 只看 Stage 2 twcert
```

## 環境變數

| 變數名稱 | 說明 | 必填 |
|:---|:---|:---:|
| `TWCERT_ACCOUNT` | TWCERT 企業會員帳號 | TWCERT 流程 |
| `TWCERT_PASSWORD` | TWCERT 企業會員密碼 | TWCERT 流程 |
| `GEMINI_API_KEY` | Google Gemini API Key | 是 |
| `GEMINI_MODEL` | Gemini 模型名稱（預設 `gemini-3.1-pro-preview`） | 否 |
| `GOOGLE_SA_JSON_B64` | Google Service Account JSON 的 Base64 編碼 | 是 |
| `GOOGLE_SA_JSON_FILE` | 或直接指定 Service Account JSON 檔案路徑 | 擇一 |
| `GOOGLE_SHEET_ID` | 情資紀錄 Google Sheet ID | 是 |
| `ASSETS_SHEET_ID` | 資產清冊 Google Sheet ID（外部表單） | 是 |
| `ASSETS_WORKSHEET` | 資產清冊工作表名稱（預設 `工作表1`） | 否 |
| `GIT_ARCHIVE_BRANCH` | IoC / JSON 存檔的 git 分支名稱（留空停用，建議 `data`） | 否 |
| `GIT_ARCHIVE_AUTO_PUSH` | 設為 `true` 時每次 commit 後自動 push（CI 用） | 否 |
| `USE_FIXTURE_DATA` | 設為 `true` 使用樣板資料開發（預設 `true`） | 否 |

## 專案結構

```
├── main.py                     # CLI 進入點
├── pyproject.toml              # uv 套件管理
├── .github/workflows/
│   ├── twcert.yml              # GitHub Actions：每 4 小時
│   └── cisa_kev.yml            # GitHub Actions：每日 UTC 09:00
├── src/
│   ├── config.py               # 環境變數與設定
│   ├── models.py               # 資料模型（IntelItem / AnalysisResult / SheetRow）
│   ├── fetchers/
│   │   ├── twcert.py           # TWCERT REST API 爬蟲（含 xlsx IoC 解析）
│   │   └── cisa_kev.py         # CISA KEV JSON 爬蟲
│   ├── analyzer/
│   │   ├── gemini.py           # Gemini API 呼叫（結構化 JSON 輸出）
│   │   └── prompt.py           # System prompt + 分析 prompt 模板
│   ├── sinks/
│   │   ├── sheets.py           # Google Sheets 讀寫（月份 tab 自動建立 / 去重 / 資產清冊載入）
│   │   └── git_archive.py      # IoC / JSON 存檔至 git archive 分支，回傳 GitHub raw URL
│   ├── parsers/
│   │   └── ioc_xlsx.py         # base64 xlsx 解析 → IP / Hash / Domain 清單 .txt
│   └── utils/
│       ├── logging.py
│       └── errors.py           # 錯誤類型與維運警報
└── tests/
    ├── fixtures/               # 樣板資料（資產清冊 / CISA KEV）
    ├── test_cisa_kev_fetcher.py
    ├── test_sheet_writeback.py
    └── test_ioc_parser.py
```

## 測試

```bash
uv run pytest tests/ -v
```

## Google Sheet 欄位規格

系統寫入 21 欄（A–U），遵循「一 CVE 一列」原則：

| 欄 | 名稱 | 填寫方式 |
|:---:|:---|:---:|
| A | 記錄日期 | 自動 |
| B | 情資編號 | 自動 |
| C | 來源 | 自動 |
| D | 情資發布日期 | 自動 |
| E | 情資主旨 | 自動 |
| F | 情資類型 | 自動 |
| G | CVE ID | 自動 |
| H | 建議措施 | AI |
| I | AI 風險等級 | AI |
| J | AI 分析摘要 | AI |
| K | 公司風險相關性 | AI 預填 |
| L | 內部受影響資產 | AI 預填 |
| M | 處置措施負責單位 | AI 預填 |
| N | 目前狀態 | 人工 |
| O | 追蹤表單連結 | 人工 |
| P | 處理備註 | 人工 |
| Q | 處理完成日期 | 人工 |
| R | 處理人員 | 人工 |
| S | 通報時間 | 自動 |
| T | TWCERT 影響等級 | 自動 |
| U | 參考網址 | 自動 |

## 部署

GitHub Actions 以 `astral-sh/setup-uv` 安裝 uv，透過 `uv sync` 還原依賴。兩個 workflow 每天 09:00 TW+8（01:00 UTC）自動觸發，傳入當天日期的 `--since`，並在執行後將 fetch JSON、analysis JSON、IoC txt push 至 `data` archive 分支。

如需固定 IP（TWCERT 後台設有白名單時），將 workflow 中的 `runs-on` 改為 `self-hosted` 即可切換至自建 Runner。

## 授權

本專案僅供內部資安防禦使用。
