# Email 發佈層設計（風險小組月信 + RD 主管內部發佈）

- 日期：2026-06-30
- 分支：`feat/email-publishing-layer`
- 狀態：設計待審

## 1. 問題陳述

現有 pipeline 把 TWCERT / CISA KEV 情資抓取、用 Gemini 分類後寫進 Google Sheets，但**到此為止就停了**。Repo 內唯一的對外通知是 `src/utils/errors.py::send_ops_alert`，且它是 log-only（不真的送出）。

需求是在「寫入 Sheet」之後新增一個**發佈層**：

1. 每月把當月「與公司相關」的情資彙整成一封信，寄給風險小組，供**月會**討論。
2. 月會中風險小組直接在 Google Sheet 上檢視與修改，並把要對外公告的情資標記為核可。
3. 會後把已核可的情資（含會議中的修訂）發佈給**全體 RD 主管**。

## 2. 目標 / 非目標

**目標**
- 兩階段、人工放行的 email 發佈流程，全部以 Python 實作並版控於本 repo。
- 沿用既有架構慣例（stage 化的 `main.py`、`src/` 子系統模組、fixture 模式、GitHub Actions 排程）。
- 第二階段發佈的內容反映「風險小組在 Sheet 上修訂後」的當前值。

**非目標（YAGNI）**
- 不做高風險急件的即時提醒（確認：**只寄月信**）。
- 不做 Slack / Teams / LINE 等其他管道。
- 不做信件回覆解析、不做 web 審核介面（核可一律在 Sheet 上操作）。
- 不改動既有每日抓取 / 分析 / 寫 Sheet 的行為。

## 3. 確認的需求

| 面向 | 決定 |
|:--|:--|
| 管道 | Email（Google Workspace / SMTP） |
| 傳輸 | SMTP（`smtp.gmail.com:587` STARTTLS + 專用寄件帳號 App Password） |
| 流程 | 兩階段、人工放行 |
| 核可訊號 | 沿用 N「狀態」欄，新增下拉值「核可發佈」 |
| 已發佈旗標 | 沿用空著的 S「通知時間」欄（非空 = 已內部發佈） |
| 風險小組信範圍 | 只送 `company_relevance != "無"` |
| 風險小組信節奏 | **月信**（每月一封 digest，會前送），與每日 pipeline 脫鉤 |
| 會議中操作 | 風險小組直接在 Sheet 檢視 / 修改 / 設「核可發佈」 |
| 內部信內容 | 摘要卡片 + 重點欄位（HTML） |
| 內部信來源 | 讀 Sheet **當前值**（含會議修訂），非原始分析 JSON |
| 內部信對象 | 全體 RD 主管（`INTERNAL_ANNOUNCE_EMAILS`） |
| 程式位置 | 新套件 `src/notifiers/`（人對人通知，與 data sink 區隔） |

## 4. 整體資料流

```
每日 pipeline（現有，不變）
  Stage1 Fetch → Stage2 Analyze → Stage3 寫 Sheet（累積進當月 YYYY-MM 分頁）

每月排程（新：notify_risk.yml）
  Stage 4a 通知風險小組
    讀當月分頁，挑 company_relevance≠無 → 一封 digest → 寄 RISK_TEAM_EMAILS
    （信中含該月 Sheet 分頁連結）
        │
        ▼  月會：風險小組在 Sheet 檢視/修改，把要發的列 N「狀態」設「核可發佈」

頻繁排程（新：publish_internal.yml）
  Stage 4b 內部發佈
    掃所有 YYYY-MM 分頁，挑（N狀態=核可發佈 且 S通知時間為空）
      → 讀當前列值渲染 HTML 摘要卡片 → 寄 INTERNAL_ANNOUNCE_EMAILS（RD 主管）
      → 回寫 S「通知時間」=now（已發佈旗標）
```

兩個新階段都是**獨立可重跑**、且與每日 pipeline 解耦。

## 5. 元件與檔案變動

| 檔案 | 變動 |
|:--|:--|
| `src/notifiers/__init__.py` | 新套件 |
| `src/notifiers/email.py` | SMTP 傳輸 + `send_risk_digest(month, rows, sheet_url)` / `send_internal_announcement(rows)`；fixture / dry-run 時不真寄，改把 HTML 存成 `src/data/email_preview_*.html` 供預覽 |
| `src/notifiers/templates.py` | `render_risk_digest(month, rows, sheet_url)`、`render_internal_cards(rows)` 兩個 HTML 樣板 |
| `src/sinks/sheets.py` | 新增 `get_rows_for_publishing()`、`mark_published(targets, ts)`、`get_month_rows(month)`、`month_tab_url(month)`；`_DROPDOWN_COLS` 的 N 欄加入「核可發佈」 |
| `src/config.py` + `.env.example` | 新 env（見 §9） |
| `main.py` | 新增 `--notify-risk`（可帶 `--month`）與 `--publish-internal` 兩個模式 |
| `.github/workflows/notify_risk.yml` | 新月排程 workflow + 手動觸發 |
| `.github/workflows/publish_internal.yml` | 新頻繁排程 workflow + 手動觸發 |
| `tests/test_email_render.py` | 樣板 / 過濾邏輯測試 |
| `tests/test_publish_scan.py` | 挑列邏輯測試（mock worksheet） |

## 6. Stage 4a — 通知風險小組（月信）

- 進入點：`main.py` 新模式 `--notify-risk`，可選 `--month YYYY-MM`（預設 = 今天 TW+8 的當月）。
- 流程：
  1. `get_month_rows(month)` 讀該月分頁全部資料列（dict per row，含欄位 A–U）。
  2. 過濾 `company_relevance != "無"`。
  3. `render_risk_digest(month, rows, sheet_url)` 產生一封 HTML digest；每筆列出：情資ID、標題、風險等級、相關性、CVE、摘要、建議措施、受影響資產、負責單位。信頭含該月 Sheet 分頁連結（`month_tab_url(month)`）。
  4. `send_risk_digest(...)` 寄給 `RISK_TEAM_EMAILS`。
- 冪等性：digest 是會前資訊性彙整，重送無害；不另設旗標。
- 跳過條件：當月無相關列、`--dry-run`、或 `RISK_TEAM_EMAILS` 未設定 → log 後跳過。

## 7. Stage 4b — 內部發佈（會後發 RD 主管）

- 進入點：`main.py` 新模式 `--publish-internal`（不需 `--source`，兩來源同在月份分頁）。
- 流程：
  1. `get_rows_for_publishing()` 掃所有 `YYYY-MM` 分頁，回傳 `狀態 == "核可發佈" 且 通知時間 為空` 的列，附帶 `(worksheet_title, row_number, row_values)` 以便回寫。
  2. 用**當前列值**（反映會議修訂）`render_internal_cards(rows)` 產生 HTML 摘要卡片：每筆一張卡，含標題、風險等級、摘要、建議措施、CVE、受影響資產。
  3. `send_internal_announcement(...)` 寄給 `INTERNAL_ANNOUNCE_EMAILS`。
  4. 寄送成功後 `mark_published(targets, now)` 對這些列回寫 S「通知時間」。
- 冪等性：S 欄非空即跳過；**先寄信成功再回寫**，回寫失敗以 `send_ops_alert` 告警（極端情況可能重寄一次，可接受）。
- dry-run / fixture 模式：渲染並輸出預覽 HTML，但**不真寄、也不回寫 S 欄**（避免把測試當成已發佈）。
- 跳過條件：無待發列、或 `INTERNAL_ANNOUNCE_EMAILS` 未設定 → log 後跳過。

## 8. Sheet 變動

- `_DROPDOWN_COLS` 的 N「狀態」欄候選值由 `待處理/處理中/已完成/不適用` 改為 `待處理/處理中/核可發佈/已完成/不適用`。
- 既有月份分頁在改版前已建立者不會自動更新下拉清單，但 `strict=False` 仍允許輸入新值；新建分頁會帶新清單。
- S「通知時間」欄語意 = 「已內部發佈時間」，沿用既有表頭「通知時間」，不改表頭。

## 9. 設定（新 env / GitHub Secrets）

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587                       # STARTTLS
SMTP_USER=secbot@company.com        # 專用寄件帳號
SMTP_PASSWORD=<app-password>        # Secret
EMAIL_FROM=資安情資Bot <secbot@company.com>
RISK_TEAM_EMAILS=a@co,b@co          # Stage 4a 收件人（逗號分隔）
INTERNAL_ANNOUNCE_EMAILS=rd-managers@co  # Stage 4b 收件人（RD 主管，可為通訊群組）
```

- `config.py` 解析逗號分隔字串為 list；空字串 → 空 list（視為未設定）。
- 本地 `USE_FIXTURE_DATA=true`（預設）→ `email.py` 不真寄，改輸出預覽 HTML 並 log。

## 10. Email 模組設計

- `email.py`：
  - `_smtp_send(subject, html, recipients) -> bool`：建立 SMTP 連線、STARTTLS、login、送 `MIMEText(html, "html", "utf-8")`；例外回傳 False 並 log。
  - `send_risk_digest(month, rows, sheet_url) -> bool`、`send_internal_announcement(rows) -> bool`：組信件主旨、呼叫渲染與傳輸；fixture/dry-run 時寫 `src/data/email_preview_{kind}_{ts}.html` 並回傳 True（視為成功，但不回寫旗標—由呼叫端依 dry-run 判斷）。
- `templates.py`：純函式，輸入 row dict / list，輸出 HTML 字串。不依賴 SMTP，易單元測試。

## 11. 錯誤處理

- 發佈層為「資料已安全進 Sheet 後」的後續動作。
- Stage 4a 寄信失敗：log + `send_ops_alert`，不讓流程以非零碼結束（資訊性月信）。
- Stage 4b 寄信失敗：**不回寫** S 欄（下次自動重試）；回寫失敗：`send_ops_alert` 告警。
- SMTP 認證 / 連線錯誤統一在 `_smtp_send` 內捕捉，回傳 False。

## 12. 測試

- `tests/test_email_render.py`：
  - `render_risk_digest` / `render_internal_cards` 輸出含關鍵欄位（標題、風險等級、CVE…）。
  - 過濾邏輯：`company_relevance == "無"` 的列不出現在風險小組 digest。
- `tests/test_publish_scan.py`：
  - mock worksheet 資料，驗證 `get_rows_for_publishing` 只挑「核可發佈 且 通知時間空」，且正確回傳 `(tab, row_number)`。
- 沿用 fixture pattern：`USE_FIXTURE_DATA` 短路真實 SMTP，CI 以外不送信。

## 13. CI Workflows

- `notify_risk.yml`：
  - `schedule`：每月一次（預設每月 1 號，可調），`workflow_dispatch`（可帶 `month` 輸入，會前手動補發）。
  - 跑 `uv run python main.py --notify-risk`（手動可加 `--month`）。
  - env：`GOOGLE_SHEET_ID`、`GOOGLE_SA_JSON_B64`、`SMTP_*`、`EMAIL_FROM`、`RISK_TEAM_EMAILS`、`USE_FIXTURE_DATA=false`。
- `publish_internal.yml`：
  - `schedule`：平日每天數次（例如 `0 1,5,9 * * 1-5` UTC），`workflow_dispatch`。
  - 跑 `uv run python main.py --publish-internal`。
  - env：同上，收件人改 `INTERNAL_ANNOUNCE_EMAILS`；需 `contents: read` 即可（不寫 archive 分支）。
- 第三方 action 沿用既有 commit SHA 釘選慣例。

## 14. 風險與注意事項

- **SMTP 寄件帳號**：建議用專用帳號 + App Password；若組織停用 App Password，需改用 OAuth/SMTP relay（屆時只動 `_smtp_send`）。
- **下拉清單回溯**：舊月份分頁不會自動帶「核可發佈」選項，但可手動輸入；如需一致可重跑 `_format_worksheet`（非本期範圍）。
- **重送風險**：Stage 4b「先寄後標記」在回寫失敗時可能重送一次，已用告警涵蓋；可接受。
- **月信月份語意**：預設當月；若月會在月初討論上個月，改用 `--notify-risk --month <上月>` 或 workflow 輸入指定。

## 15. 開放問題

- 月信排程的確切日期（每月幾號）與內部發佈掃描頻率，待部署時依實際月會時間在 workflow cron 微調；預設值如 §13。
