# Sheet Schema Realign — 對齊「威脅情資管理列表」pool + 月分頁

- 日期：2026-07-01
- 分支：`feat/sheets-adc`(已含 ADC 改動:`config.get_service_account_path` 回 None、`sheets._ensure_client` 走 `google.auth.default` fallback、`tests/test_sa_creds.py`)
- 狀態：設計已定,待實作

## 1. 背景與目標

實際營運 Sheet 是 `威脅情資管理列表_2026`(id `1bZYtndY1wqHeDeYT_2ig_CgOpVVcepnnM7qYGGk62Lc`),結構與 bot 內建的 21 欄 A–U(`INTEL_HEADERS`)完全不同。要把 bot 改成寫進這個檔:

- **新情資 → 先 append raw 到 pool 分頁**,Gemini 分析後 **回填 pool 同一列**。
- 分析後 **相關性 ≠ 無** 的筆 → **複製到月分頁 `2026/MM`**(供風險小組討論)。
- 月分頁的 `狀態=核可發佈` + 空 `通知時間` 觸發內部發佈,寄出回寫 `通知時間`。

## 2. 欄位與值對照(唯一事實來源)

### POOL 分頁（tab 名 = env `POOL_WORKSHEET`，預設 `2026_威脅情資表`）
既有 8 欄,順序固定(bot 依「欄位位置」寫,不動既有標題):

| idx | 欄位 | 內容 | 階段 |
|:--|:--|:--|:--|
| 0 (A) | 記錄日期 | 寫入日期 `YYYY-MM-DD` | 抓取 append |
| 1 (B) | 情資編號 | `intel_id`(**pool 去重鍵**) | 抓取 append |
| 2 (C) | 情資發布日期 | `publish_date` | 抓取 append |
| 3 (D) | 情資內容 | `title` | 抓取 append |
| 4 (E) | 建議措施 | Gemini `recommendation` | 分析回填 |
| 5 (F) | 公司風險相關性 (H/M/L) | 相關性中文標籤(見下) | 分析回填 |
| 6 (G) | 內部受影響資產 | `", ".join(affected_assets)` | 分析回填 |
| 7 (H) | 處置措施負責單位 | Gemini `responsible_unit` | 分析回填 |

抓取時 E–H 留空字串;分析回填只更新 E–H(range `E{row}:H{row}`)。

### MONTHLY 分頁（tab 名 `YYYY/MM`，斜線）
10 欄(bot 建立分頁時寫入這組標題;讀取一律**依欄位位置**,不靠標題字串):

| idx | 欄位 | 內容 |
|:--|:--|:--|
| 0 (A) | 情資編號 | `intel_id`(**月分頁去重鍵**) |
| 1 (B) | 情資發布日期 | `publish_date` |
| 2 (C) | 情資內容 | `title` |
| 3 (D) | 建議措施 | Gemini `recommendation` |
| 4 (E) | 風險相關性 (H/M/L) | 相關性中文標籤 |
| 5 (F) | 內部受影響資產 | `", ".join(affected_assets)` |
| 6 (G) | 處置措施負責單位 | Gemini `responsible_unit` |
| 7 (H) | 追蹤表單連結 | 留空(人工) |
| 8 (I) | 狀態 | bot 寫 `待處理`;下拉:待處理/處理中/核可發佈/已完成/不適用 |
| 9 (J) | 通知時間 | 內部發佈後回寫(已發佈旗標) |

只寫 `相關性 != 無` 的筆。

### 相關性中文標籤對照
`{"H": "高相關", "M": "中相關", "L": "低相關", "無": "無"}`
(「重大相關」為風險小組人工升級選項,bot 不自動判;不寫 Critical/High 絕對風險等級。)

## 3. 行為

- **月分頁命名**:`YYYY/MM`(斜線),由 `publish_date` 決定;無日期時用當月 TW+8。
- **不重排分頁**:移除 `_sort_worksheets_newest_first`(及其呼叫),不動使用者分頁順序。
- **去重**:pool 依 `情資編號`(col B);月分頁依 `情資編號`(col A)。
- **pool 分頁必須已存在**(使用者維護);缺少時丟明確錯誤,**不自動建立/格式化**。
- **月分頁**缺少時 bot 自動建立(寫 10 欄標題 + 狀態下拉),**不重排**。
- **email 讀月分頁**:依位置取值,回傳固定鍵 dict:`情資編號/情資發布日期/情資內容/建議措施/相關性/受影響資產/負責單位/狀態/通知時間`。

## 4. 檔案變動

| 檔案 | 變動 |
|:--|:--|
| `src/config.py` | 加 `POOL_WORKSHEET`(預設 `2026_威脅情資表`)。(ADC 的 `get_service_account_path`→None 已完成) |
| `src/sinks/sheets.py` | 移除 21 欄 `INTEL_HEADERS`/`_COL_WIDTHS`/`append_rows`/`_get_or_create_date_worksheet`/`_sort_worksheets_newest_first`/舊 `_format_worksheet`/`_resolve_date_tab`(dash)。新增:`POOL_HEADERS`、`MONTHLY_HEADERS`、`_RELEVANCE_LABELS`、`relevance_label()`、`append_pool_raw(items)`、`backfill_pool_analysis(pairs)`、`append_monthly(pairs)`、月分頁 `_get_or_create_month_ws`(斜線、狀態下拉、不重排)。改 `get_existing_intel_ids`→ pool 去重(col B)、`get_month_ids`(月分頁 col A)、`get_month_rows`(位置→固定鍵 dict)、`get_rows_for_publishing`(斜線 tab、col I/J)、`mark_published`(寫 col J)、`select_relevant`/`select_publishable`(新鍵)。 |
| `src/models.py` | 移除 `SheetRow`(及 `from_intel_and_analysis`/`to_row_list`)。保留 `IntelItem`/`AnalysisResult`。 |
| `main.py` | 重寫 pipeline:fetch → `append_pool_raw` → analyze(新筆)→ `backfill_pool_analysis` + `append_monthly`。移除舊 `stage_write_sheet`/`SheetRow`/IoC 回填到 recommendation。`stage_notify_risk`/`stage_publish_internal` 改讀新月分頁(斜線 tab、新鍵);`--month` 預設當月改斜線格式。 |
| `src/notifiers/templates.py` | 依月分頁欄位重建 `render_risk_digest`(表格:情資編號/情資內容/相關性/建議措施/受影響資產/負責單位)與 `render_internal_cards`(卡片:同欄位)。 |
| `tests/*` | 改寫 `test_sheet_writeback.py`(SheetRow 移除→改測 relevance_label + pool/monthly value builder)、`test_publish_scan.py`(新鍵、月分頁 col I/J、斜線 tab)、`test_email_render.py`(新欄位 + 欄位守衛改對照 POOL/MONTHLY headers)、`test_email_send.py`(記錄 dict 新鍵)。 |
| `docs/cloudrun-deploy.md` | 移除 `GOOGLE_SA_JSON_B64`(改 ADC 說明),加 `POOL_WORKSHEET` env;§6/§10 job env 補 `POOL_WORKSHEET` 與 `GOOGLE_SHEET_ID`。 |

## 5. 測試策略

- 純函式測試(不碰 gspread):`relevance_label` 對照;pool value builder(抓取列 = [now, id, date, title, "","","",""])、backfill builder(= [reco, label, assets, unit]);monthly value builder(= [id,date,title,reco,label,assets,unit,"","待處理",""] 且只含相關性≠無);`select_relevant`/`select_publishable` 用新鍵 + 位置語義。
- I/O wrapper(append_pool_raw/backfill/append_monthly/get_* /mark_published)沿用 repo 慣例不寫單元測試,以 import + lint 驗證。
- 全套 `uv run pytest` 綠、`ruff check`/`format --check` 綠。

## 6. 部署 / 測試目標

- 先在 **`2026/06`**(空分頁)驗:用 6 月情資(`--since 2026-06-01`)讓月分頁落在 `2026/06`。
- pool(`2026_威脅情資表`)含真實資料;端到端實測會 append 測試列到 pool,需使用者同意(可事後刪)。
- Sheets 認證走 **ADC**(runtime SA `intel-bot`),需該 SA 被加入 Sheet 共用 + 專案啟用 Sheets/Drive API。

## 7. 風險

- 月分頁既有標題含換行;bot 建立新分頁時寫**單行**標題,讀取一律**依位置**,避免換行字串比對脆弱。
- pool 回填以 `情資編號→列號` 對映(讀 col B),同 run 內即可;跨 run resume 靠去重不重覆 append。
- 相關性標籤與使用者下拉需一致(`高相關/中相關/低相關/無`);使用者下拉若含「重大相關」不影響 bot 寫入。
