# 喆律儀表板維運手冊

> 維護儀表板的人請從這裡開始。共 9 個頁面、5 個自動排程、若干手動上傳；下面把「自動跑」「要動」「業務維護」三類分開列。

---

## 一、9 個頁面 × 資料更新狀態

| 頁面 | 主資料源 | 更新方式 | 延遲 / 痛點 |
|---|---|---|---|
| **諮詢分析** | `consultation_cases` / `monthly_stats` | ✅ 全自動 — GitHub Actions `update-stats.yml`，每日 12:00 + 00:00 抓 CRM | 即時；transcript 內容需手動上傳 ZIP 補 |
| **營運** | `consultation_cases`（成案/結案）+ `revenue_records` | ✅ 全自動 — `update-cases.yml` 每日 03:30 + 週日 refresh-open；`update-revenue.yml` 每日 12:00/00:00 | 即時；頁上有「立即手動同步」按鈕 |
| **法律顧問** | `advisor_cases` + `advisor_transactions` + `advisor_inbound` + `cold_call_visits` | ⚠️ 半自動：CRM 對帳每日；成案清單/inbound/陌開靠 Apps Script 每日 02:00 從 Google Sheet 同步 | **客戶集合**由「法顧成案清單」Sheet 定義，業務手動維護 |
| **委前漏斗** | `consult_oa_funnel_daily` + `consult_oa_monthly_funnel` + `consult_oa_tag_chats_monthly` | ⚠️ 部分自動：① LINE follower 每日 `consult_funnel_sync` ② 月度場次/leads 每週一 09:00 Apps Script | **OA 標籤聊天室數**每月初要手動進儀表板輸入 |
| **法律 010** | `raw_010_*` + `fact_010_monthly_*` | ✅ 全自動 — `sync-010.yml` 每日 09:00 從 Google Sheet「法律010總表」 | sheet `meeting_date` 業務從未填 |
| **合署律師** | `public/partners/index.html` 內 `<script id="embedded-data">` | ❌ **手動觸發** — 儀表板上按「立即同步」呼叫 `sync-partners.yml` 抓 Drive xlsx | 律師月底才回填上月（4/29 填 3 月、5/29 填 4 月） |
| **財務規劃** | `finance_data` + `finance_employees` + `finance_adjustments` | ❌ **完全手動** — admin 在儀表板上傳 Excel + 輸入調整項 | 月底會計結帳才有 actual |
| **OKR 追蹤** | 上述各表 + `okr_targets` | ✅ 派生資料（依其他表自動算） | KR target 數字要在 admin 頁設定 |
| **帳號管理** | `lawyers` 表 | 手動（新人來才動） | — |

---

## 二、自動排程清單

| # | 名稱 | 在哪設定 | 跑什麼 | 排程（台北時間） |
|---|---|---|---|---|
| 1 | `update-stats.yml` | GitHub Actions | `daily_update.py`（諮詢統計 + 案件） | 12:00、00:00 |
| 2 | `update-cases.yml` | GitHub Actions | `scrape_case_lists.py recent`；週日跑 `refresh-open` | 每日 03:30；週日 04:00 |
| 3 | `update-revenue.yml` | GitHub Actions | `scrape_reconciliation.py` + `scrape_advisor_transactions.py` | 12:00、00:00 |
| 4 | `sync-010.yml` | GitHub Actions | `sync_010.py`（法律010總表 → Supabase） | 09:00 |
| 5 | `consult_funnel_sync` | Supabase Edge Function（pg_cron） | LINE Messaging API → `consult_oa_funnel_daily` | 09:00 |
| 6 | `advisor_sync.gs` | 「法顧成案清單」Sheet 的 Apps Script | 3 分頁 → `advisor_cases` / `advisor_inbound` / `cold_call_visits` | 每日 02:00 |
| 7 | `consult_oa_monthly_sync.gs` | 「委前各項數據追蹤表單」的 Apps Script | 月度場次/leads → `consult_oa_monthly_funnel` | 每週一 09:00 |
| 8 | `sync-partners.yml` | GitHub Actions | 抓 Drive xlsx → embed 進 `partners/index.html` | **無 cron**，按按鈕觸發 |
| 9 | `deploy-pages.yml` | GitHub Actions | push main → 部署 GitHub Pages | push 觸發 |

---

## 三、第二層：手動維運

### A. 每月固定動作（建議排進月底 routine）

| 項目 | 頁面 | 操作位置 | 來源 |
|---|---|---|---|
| 上傳上月損益表 actual | 財務規劃 | 「上傳損益表 Excel」（選「實際支出」） | 會計月結 |
| 上傳薪資表（114/115） | 財務規劃 | 「上傳薪資表 Excel」 | 人資 |
| 觸發合署同步（律師回填後） | 合署律師 | 「立即同步」按鈕 | Drive 共用資料夾 |
| 輸入 LINE 標籤聊天室數 | 委前漏斗 | 「✏️ 編輯 OA 月份標籤聊天室數」modal | LINE OA Manager → 聊天設定 → 標籤 → 「115年MM月」 |
| 更新 OKR target | OKR | OKR 設定頁 | 年初/季初 |

### B. 業務團隊維護（不是 admin 動，但要知道誰負責）

| 項目 | 維護者 | Source-of-truth |
|---|---|---|
| 法顧成案清單（定義客戶集合） | 業務 | 「法顧成案清單」Google Sheet |
| inbound 數據 | 業務 | 同上 sheet |
| 電話陌開拜訪進度 | 業務 | 同上 sheet |
| 委前各項數據追蹤表單（49 分頁） | 委前團隊 | Google Sheet |
| 法律 010 總表 | 010 團隊 | Google Sheet（18 分頁；`meeting_date` 沒在填） |
| 合署律師案件明細 xlsx | 13 位合署律師 | Drive 16【財務】資料夾，月底回填 |

### C. 不定期 / 觸發式

| 情境 | 動作 |
|---|---|
| 加新合署律師 | 改 3 處 hardcoded 名單：`scripts/partners/drive_client.py` / `parse_senior.py` / `build_embedded.py` |
| 新人進來 / 離職 | `lawyers` 表（帳號管理頁）；財務頁開「人員異動」表單套薪資/年終影響 |
| 法務部門異動 | `scripts/compute_lawyer_departments.py` |
| 諮詢 transcript 內容缺 | 諮詢分析 → 資料上傳 tab → 上傳 ZIP（檔名 `律師_成案_日期_案件類型(當事人)_會議記錄.docx`） |
| LINE channel token 過期 | Supabase 改 `consult_oa_credentials.line_channel_token` |
| Google service account 換 key | GitHub Secrets `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` |
| Supabase MCP token 過期 | **2026-08-11 到期**，要重發 |

---

## 四、結構性限制（沒辦法靠維運解決）

1. **合署資料天生延遲一個月** — 律師月底才填，沒辦法即時，這是業務流程不是技術問題
2. **010 sheet `meeting_date` 永遠是空的** — 改用 `intake_date → first_payment_date` 近似，要 010 團隊改 SOP 才解
3. **法顧客戶集合不能自動推 CRM** — 業務指示：CRM 儲值有但 sheet 沒登的不計入法顧（避免污染）
4. **finance actual 要等月結** — 大概每月 5-10 號才有上個月完整損益表
5. **諮詢 transcript** — CRM 沒所有會議記錄，部分案件 brief 分析要靠手動 ZIP 補

---

## 五、健康度檢查

### 5.1 儀表板內

財務規劃頁底部有「資料新鮮度」表格，顯示 `finance_data (actual)` / `finance_data (budget)` / `revenue_records` / `fact_010_monthly_team` / `advisor_transactions` / `advisor_cases` / `partners JSON` 燈號。

或進入**維運清單**頁（admin 限定，nav 上 🛠 圖示）看一站式總覽。

### 5.2 終端機

```bash
gh run list --workflow=update-stats.yml --limit 5
gh run list --workflow=update-cases.yml --limit 5
gh run list --workflow=update-revenue.yml --limit 5
gh run list --workflow=sync-010.yml --limit 5
gh run list --workflow=sync-partners.yml --limit 5
```

失敗的 run 進去看 logs：

```bash
gh run view <run-id> --log-failed
```

### 5.3 Apps Script

Apps Script 失敗不會自動通知；每月看一次：
- 「法顧成案清單」Sheet → 擴充功能 → Apps Script → 執行紀錄
- 「委前各項數據追蹤表單」Sheet → 擴充功能 → Apps Script → 執行紀錄

### 5.4 Supabase Edge Function

```
https://supabase.com/dashboard/project/zpbkeyhxyykbvownrngf/functions
```

點 `consult_funnel_sync` → Logs → 看每天 09:00 的執行結果。

---

## 六、相關文件

- `CLAUDE.md` — 專案概覽與架構慣例
- `ONBOARDING.md` — 新人上手
- `scripts/apps_script/SETUP.md` — 法顧 Apps Script 安裝 SOP
- `scripts/apps_script/CONSULT_OA_SYNC_SETUP.md` — 委前漏斗 Apps Script 安裝 SOP
- `supabase/SETUP.md` — Supabase 設置

> 文件最後更新：2026-05-27
