# 資安威脅情資 AI 自動化分析與應變計劃書

**專案名稱：** TWCERT/CC 企業情資自動化處理系統  
**核心驅動：** Python + Google Gemini 3.1 API  
**情資來源：** TWCERT/CC 企業後台（每 4 小時）、CISA KEV（每日一次）

---

## 一、開發工具 (Development Tools)

本系統旨在透過自動化流程，消除人工登入、比對與評估的重複性勞動。

### 自動化擷取引擎

- **Python 3.11+** 作為基礎架構
- **TWCERT 爬蟲**：Playwright 模擬企業會員登入，自動處理身份驗證並抓取「接獲情資」列表，每 4 小時執行一次
- **CISA KEV 爬蟲**：直接呼叫 CISA 官方 JSON Feed（`requests`），無需瀏覽器，每日 UTC 09:00 執行一次，自動篩選當日新增項目

### AI 邏輯推理中心

- **Google Gemini 3.1 Pro (Preview)**：利用長文本處理與邏輯分析能力，解讀非結構化情資並與內部規章進行語義對齊
  - Model string：`gemini-3.1-pro-preview`
  - 建議定期追蹤 Stable 版本釋出，適時從 Preview 遷移以確保 SLA 保障

### 數據與通報介面

- **Google Sheets API (gspread)**：同步讀取公司資產清單，並回填風險評估結果
- **Google Drive API**：上傳 IoC txt 封鎖清單至指定資料夾，與 Sheets 共用同一組 Service Account 憑證，無需額外設定
- **Mattermost Webhook**：即時發送結構化警訊至資安頻道

---

## 二、維運構想 (Operation & Maintenance)

系統採模組化設計，確保在無人值守情況下穩定執行。

### 作業流程 (Workflow)

系統採雙來源設計，兩個爬蟲各自獨立排程，共用 AI 分析與通報模組。

**TWCERT 流程（每 4 小時）**

1. **觸發**：GitHub Actions Cron（`0 */4 * * *`）啟動
2. **爬取**：Playwright 登入 TWCERT 企業後台，抓取最新情資列表與內頁詳情
3. **去重**：比對 Google Sheet B 欄已存在的情資編號，跳過重複項目
4. **整合**：從 Google Sheet 載入公司資產清單，與情資進行比對
5. **AI 分析**：呼叫 Gemini 3.1，產出風險分級、摘要與建議措施
6. **派發**：High / Critical 即時通報 Mattermost，結果回填 Google Sheet
7. **IoC 提取**：若情資附件含 IP 封鎖清單（如 xlsx），自動解析並產出 `ioc_<情資編號>.txt`，上傳至 Google Drive IoC 專用資料夾，並於 Mattermost 通報中附上下載連結

**CISA KEV 流程（每日一次）**

1. **觸發**：GitHub Actions Cron（`0 9 * * *`，台灣時間 17:00）啟動
2. **抓取**：直接下載 CISA KEV JSON Feed，篩選當日新增 CVE
3. **去重**：比對 Google Sheet 已存在的 CVE ID，跳過重複項目
4. **AI 分析**：與 TWCERT 共用同一分析模組
5. **派發**：High / Critical 即時通報，結果回填 Google Sheet

### 錯誤監控

- **登入失敗預警**：TWCERT 後台更動導致爬蟲失效時，發送維修通報
- **API 消耗控管**：每日監控 Gemini API 額度使用量，確保符合預算

---

## 三、作業流程圖 (Workflow Diagram)

![資安威脅情資 AI 自動化處理流程](flowchart_gdocs.png)

---

## 四、情資紀錄表規格 (Google Sheet Schema)

系統將所有分析結果統一寫入 Google Sheet，作為情資追蹤與處置的主要工作介面。

### 欄位定義

| 欄 | 欄位名稱 | 填寫方式 | 說明 |
| :---: | :--- | :---: | :--- |
| A | 記錄日期 | 自動 | 系統寫入時間戳記 |
| B | 情資編號 | 自動 | TWISAC-YYYYMM-XXXX-N（多 CVE 拆列時加流水號） |
| C | 來源 | 自動 | `TWCERT` / `CISA_KEV` |
| D | 情資發布日期 | 自動 | 原始情資發布時間 |
| E | 情資主旨 | 自動 | 情資標題摘要 |
| F | 情資類型 | 自動 | 101-漏洞訊息 / IoC / 其他 |
| G | CVE ID | 自動 | 單一 CVE，一筆情資含多 CVE 時拆為多列 |
| H | 建議措施 | AI 自動 | 具體修補或因應步驟；若含 IP 封鎖建議則附 Google Drive 下載連結 |
| I | AI 風險等級 | AI 自動 | `Critical` / `High` / `Medium` / `Low` / `無` |
| J | AI 分析摘要 | AI 自動 | 2–3 句風險說明 |
| K | 公司風險相關性 | AI 預填，人工確認 | `H` / `M` / `L` / `無` |
| L | 內部受影響資產 | AI 預填，人工確認 | 對應公司資產分類 |
| M | 處置措施負責單位 | AI 預填，人工確認 | 對應內部單位清單 |
| N | 目前狀態 | 人工 | `待處理` / `處理中` / `已完成` / `不適用` |
| O | 追蹤表單連結 | 人工 | Redmine ticket / GitLab issue / Jira 等外部追蹤系統連結 |
| P | 處理備註 | 人工 | 處理過程說明、決策依據 |
| Q | 處理完成日期 | 人工 | 實際完成修補或結案日期 |
| R | 處理人員 | 人工 | 負責處理的人員姓名 |
| S | 通報時間 | 自動 | Mattermost 發送時間（未通報則空白） |
| T | 參考連結 | 自動 | NVD / 廠商公告 URL |

### 設計原則

- **一 CVE 一列**：同一份情資若包含多個 CVE，自動拆為多列分別追蹤，確保每個漏洞都有獨立的處置狀態
- **去重機制**：以 B 欄情資編號為唯一鍵，重複執行時自動跳過已存在的項目，不重複寫入或觸發 Gemini 分析
- **AI 預填 + 人工確認**：K / L / M 欄由 AI 根據公司資產清單初步判斷，人工僅需確認或修正，降低人工作業量
- **追蹤表單連結**：O 欄供負責單位填入 Redmine ticket / GitLab issue 等外部系統連結，串聯情資通報與修補追蹤流程
- **處理紀錄內嵌**：Q / R / S 欄作為輕量化處理紀錄，記錄最終處置結果
- **IoC 附件提取**：情資若附帶 IP 封鎖清單（xlsx 格式），系統自動解析產出純文字 `.txt` 檔，上傳至 Google Drive IoC 資料夾（與 Sheets 共用 Service Account），Mattermost 通報附上 Drive 連結供防火牆人員直接下載匯入，不進入 Gemini 分析流程

---

## 五、部署方式 (Deployment)

### 建議路徑

```
POC 階段                    正式階段
─────────────               ──────────────────────────────
GitHub Actions          →   GitHub Actions
（浮動 IP，快速驗證）         + Self-hosted Runner（視需求升級）
```

POC 階段直接使用 GitHub Actions 即可，不需要額外基礎設施。

### 執行環境比較

| 方式 | 成本 | IP 固定 | 維護難度 | 適合情境 |
| :--- | :--- | :--- | :--- | :--- |
| **GitHub Actions**（預設） | 免費額度內 | 否 | 極低 | POC 驗證階段 |
| **Self-hosted Runner** | 低（用現有機器） | 是 | 低 | 正式上線後 |
| **公司內部 VM + Cron** | 低 | 是 | 低 | 已有機房資源 |
| **GCP Cloud Run Jobs** | 低 | 可配靜態 IP | 低 | 無機房、純雲端 |
| **Docker on NAS** | 極低 | 是 | 低 | 公司有 Synology 等 NAS |

### GitHub Actions Workflow 範例

兩個來源各自獨立 workflow，頻率分開設定，共用同一份程式碼庫。

**twcert.yml（每 4 小時）**

```yaml
name: TWCERT 情資分析
on:
  schedule:
    - cron: '0 */4 * * *'
  workflow_dispatch:
jobs:
  analyze:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: playwright install chromium --with-deps
      - name: Run TWCERT fetcher
        env:
          TWCERT_ACCOUNT:     ${{ secrets.TWCERT_ACCOUNT }}
          TWCERT_PASSWORD:    ${{ secrets.TWCERT_PASSWORD }}
          GEMINI_API_KEY:     ${{ secrets.GEMINI_API_KEY }}
          GOOGLE_SHEET_ID:    ${{ secrets.GOOGLE_SHEET_ID }}
          MATTERMOST_WEBHOOK: ${{ secrets.MATTERMOST_WEBHOOK }}
        run: python main.py --source twcert
```

**cisa_kev.yml（每日 UTC 09:00）**

```yaml
name: CISA KEV 情資分析
on:
  schedule:
    - cron: '0 9 * * *'
  workflow_dispatch:
jobs:
  analyze:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
        # 不需要安裝 Playwright，CISA KEV 使用純 requests
      - name: Run CISA KEV fetcher
        env:
          GEMINI_API_KEY:     ${{ secrets.GEMINI_API_KEY }}
          GOOGLE_SHEET_ID:    ${{ secrets.GOOGLE_SHEET_ID }}
          MATTERMOST_WEBHOOK: ${{ secrets.MATTERMOST_WEBHOOK }}
        run: python main.py --source cisa_kev
```

### 升級至 Self-hosted Runner（三步驟）

```bash
# 1. GitHub repo → Settings → Actions → Runners → New self-hosted runner

# 2. 下載並設定 Runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/your-org/your-repo --token YOUR_TOKEN

# 3. 註冊為系統服務（開機自啟）
sudo ./svc.sh install && sudo ./svc.sh start
```

Workflow 只需將 `runs-on` 改為 `self-hosted` 即可，其餘不變。

### 待確認項目

> **[ ] TWCERT 企業後台是否設有 IP 存取限制（白名單）？**
> - 確認方式：使用非公司網路（手機熱點）嘗試登入後台
> - 若**無限制**：GitHub Actions 預設方案即可，無需調整
> - 若**有限制**：改用 Self-hosted Runner 部署於固定 IP 機器

---

## 六、成本預估 (Cost Estimation)

以下以每日 6 次執行、每次處理約 10 筆情資為基準估算。

### API 用量假設

| 項目 | 假設值 |
| :--- | :--- |
| 每次執行情資筆數 | 約 10 筆 |
| 每筆 Prompt 大小 | 約 2,000 tokens（情資 + 資產 + 規章） |
| 每筆 Output 大小 | 約 500 tokens（分析報告） |
| 每日執行次數 | 6 次 |
| 每月執行次數 | 約 180 次 |

### 月費估算

| 服務 | 計費方式 | 月用量估算 | 月費估算（USD） |
| :--- | :--- | :--- | :--- |
| **Gemini 3.1 Pro API** | Input $1.25 / 1M tokens；Output $10 / 1M tokens | Input：3.6M tokens；Output：0.9M tokens | **~$13.5** |
| **Google Sheets API** | 免費（10M cells / 分鐘） | 遠低於免費額度 | **$0** |
| **GitHub Actions** | 免費 2,000 分鐘 / 月；超出 $0.008 / 分鐘 | 約 90 分鐘（每次 30 秒） | **$0** |
| **Mattermost** | 自架免費；雲端方案另計 | — | **$0（自架）** |
| **執行環境（Self-hosted）** | 使用現有機器 | — | **$0** |

> 月費合計約 **USD $13.5 / 月（約 NTD $430）**

### 情境試算

| 情境 | 每日情資筆數 | 月費估算（USD） |
| :--- | :--- | :--- |
| **低量**（目前假設） | 10 筆 | ~$13.5 |
| **中量** | 30 筆 | ~$40 |
| **高量** | 100 筆 | ~$135 |

### 成本控制建議

- **設定每日 API 用量上限**：於 Google AI Studio 設定 Quota 警示，超出閾值自動停止並通報
- **快取靜態內容**：資產清單與風險規章每日僅需從 Google Sheet 讀取一次，快取後重複使用於 6 個週期，可顯著降低 token 消耗
- **依風險等級過濾**：若情資標題已明顯不相關（如境外事件），可在進入 Gemini 分析前以關鍵字預篩，減少不必要的 API 呼叫

---

## 七、預期效益 (Expected Benefits)

| 指標項目 | 轉型前（人工處理） | 轉型後（AI 自動化） | 改善幅度 |
| :--- | :--- | :--- | :--- |
| **處理耗時** | 20 分鐘 / 次 | < 1 分鐘 / 次 | **95% 效率提升** |
| **執行頻率** | 依人力排程（易延遲） | 嚴格每 4 小時執行 | **即時性大幅提升** |
| **判斷標準** | 依個人經驗（易波動） | 依 AI + 規章（一致性） | **決策品質穩定** |
| **稽核軌跡** | 手動記錄（易疏漏） | 全自動 Google Sheet 存檔 | **100% 留痕** |

---

## 八、資安確認 (Security Confirmation)

### 合法合規性

- **工具授權**：使用之開源框架符合 MIT / Apache 2.0 授權
- **情資來源**：透過合法企業會員帳號存取，僅限內部資安防禦使用

### 數據隱私與防護

- **API 安全**：使用公司核發之 Gemini 3.1 API，啟用「資料不訓練（Data not used for training）」條款，確保情資與資產不外洩至公有模型
- **密鑰管理**：帳密與 API Key 存放於環境變數（Environment Variables），禁止寫死於代碼

### 網路配置

- 腳本執行環境限制於公司內部 IP 或受信任之雲端 IP 區間
- TWCERT 後台是否設有 IP 白名單限制，**待確認**（見第五節）

---

## 九、專案里程碑

### Phase 1｜環境準備與驗證（Week 1）

- [ ] 確認 TWCERT 企業後台是否設有 IP 存取限制（白名單）
- [ ] 建立 GitHub repo 與 Actions workflow 基礎架構
- [ ] 設定 GitHub Secrets（TWCERT 帳密、API Keys）
- [ ] 確認 Gemini 3.1 Pro API 企業授權啟用狀態

### Phase 2｜爬蟲開發（Week 2）

- [ ] 完成 Playwright 自動登入 TWCERT 後台
- [ ] 實作情資列表擷取與內頁詳情抓取
- [ ] 建立登入失敗偵測與 Mattermost 維修通報機制
- [ ] 本地端爬蟲測試通過

### Phase 3｜AI 分析核心（Week 3）

- [ ] 設計 Gemini 3.1 Prompt 模板（情資 + 資產 + 規章三方比對）
- [ ] 調優 Prompt，確認分級輸出格式（High / Critical / Medium / Low）
- [ ] 確認 model string 使用 `gemini-3.1-pro-preview`
- [ ] 單元測試：模擬情資輸入，驗證分析結果正確性

### Phase 4｜資料整合（Week 4）

- [ ] 串接 Google Sheets API，實作資產清單讀取
- [ ] 建立 Google Drive IoC 專用資料夾，設定公司內部存取權限
- [ ] 依 20 欄 Schema 實作分析結果回填（含去重、CVE 拆列邏輯）
- [ ] 實作 K / L / M 欄 AI 預填（公司風險相關性、受影響資產、負責單位）
- [ ] 建立 API 每日用量記錄與 Quota 警示機制
- [ ] 端對端整合測試（TWCERT + CISA KEV → AI 分析 → Sheet 回填）

### Phase 5｜通報與部署（Week 5）

- [ ] 完成 Mattermost Webhook 警報推送（High / Critical 分級通報）
- [ ] 設定 GitHub Actions Cron（每 4 小時）
- [ ] 執行完整 Staging 測試，驗證六個週期穩定運行
- [ ] 視 IP 限制確認結果，決定是否切換至 Self-hosted Runner

### Phase 6｜上線與優化（Week 6）

- [ ] 正式上線，切換至生產環境
- [ ] 觀察首周運行狀況，記錄異常與誤判案例
- [ ] 根據實際情資量調整 Prompt 與成本控制參數
- [ ] 撰寫維運 SOP 文件，完成交接
