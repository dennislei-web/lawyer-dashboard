# 喆律法律事務所 儀表板專案

## 專案概覽

喆律法律事務所內部 Web App，含多個獨立儀表板：
- **諮詢分析** (`public/index.html`) — 律師諮詢案件分析、簽約率、年度追蹤、未成案追蹤
- **營運** (`public/revenue/index.html`) — 營收、部門分析、來源分析、合署律師統計
- **財務規劃** (`public/finance/index.html`) — 損益表、預算編列、實際 vs 預算、人事異動成本分析
- **法律顧問** (`public/advisor/index.html`) — 法顧成案清單、進案/續委任分析、客戶 360、inbound 漏斗、陌開拜訪
- **合署律師** (`public/partners/index.html`) — 合署律師案件 / 財務

## 架構

- **前端**：純 HTML/JS 單檔 SPA（每個儀表板一個 `index.html`），無 bundler，用 CDN 載入 Supabase JS、Chart.js、SheetJS
- **後端**：Supabase（Auth + PostgreSQL + RLS）
- **部署**：GitHub Pages（自動 workflow `.github/workflows/deploy-pages.yml`）
- **自動更新**：GitHub Actions workflows 呼叫 Python 腳本每日/每月同步資料

**Supabase 連線資訊**（在前端程式碼內）：
```
URL:  https://zpbkeyhxyykbvownrngf.supabase.co
Key:  sb_publishable_NvTWZM6IGgc_Jn8iCXFvaA_QnvJsstM  (anon key)
```

Python 腳本需在 `scripts/.env` 設定 `SUPABASE_SERVICE_KEY`（service_role key，繞過 RLS）。

## 資料夾結構

```
public/
  index.html              # 諮詢分析儀表板
  revenue/index.html      # 營運儀表板
  finance/index.html      # 財務規劃儀表板
supabase/
  migrations/             # 版本化 SQL migration（時間戳命名 YYYYMMDDHHMMSS_*.sql）
  SETUP.md                # Supabase 設置說明
scripts/
  update_supabase.py      # xlsx → Supabase 同步（諮詢資料）
  daily_update.py         # 每日自動更新
  monthly_import.py       # 每月資料匯入
  seed_revenue_data.py    # 營收資料 seed
  create_auth_users.py    # 批次建立 Auth 使用者
  setup_admin.py          # 建立 admin 帳號
.github/workflows/
  deploy-pages.yml        # 推到 main → 部署到 GitHub Pages
  update-stats.yml        # 諮詢統計每日更新
  update-revenue.yml      # 營收資料同步
netlify.toml              # 備用部署設定（目前主要用 GitHub Pages）
```

## 關鍵資料表（Supabase）

| 表 | 用途 |
|----|------|
| `lawyers` | 律師/使用者 profile + Auth 連結（role: admin/lawyer/manager）|
| `monthly_stats` | 月度諮詢統計（每律師） |
| `consultation_cases` | 諮詢案件明細 |
| `sync_status` | 同步狀態記錄 |
| `revenue_records` | 營收逐筆記錄 |
| `departments` / `department_members` | 部門與成員 |
| `monthly_revenue_stats` | 月度營收統計 |
| `finance_categories` | 損益表科目（35筆）|
| `finance_data` | 預算/歷史/實際財務數字 |
| `finance_adjustments` | 預算調整項（離職、新進、育嬰留停等）|
| `finance_employees` | 員工薪資名冊（每年一版）|
| `finance_uploads` | Excel 上傳紀錄 |

RLS 規則：登入使用者可讀，admin 可寫。Python 腳本用 service_role key 繞過 RLS。

## 核心慣例

### UI 模式
- **CSS 變數**：深色主題為主，`[data-theme="light"]` 切淺色。所有顏色用 `var(--gold)`, `var(--blue)`, `var(--red)` 等
- **單檔架構**：每個儀表板整合 HTML + CSS + JS 在同一個 `index.html`
- **Chart.js**：趨勢圖、圓餅圖、長條圖
- **SheetJS (xlsx)**：Excel 上傳解析
- **Tab 切換**：`.tab-btn` + `.page.active`
- **表格**：`.table-card`, `.section-row`, `.subtotal-row`, `.net-row`
- **狀態標示**：`.text-green`（好/低於預算）、`.text-red`（差/超出預算）、`.text-gold`（強調）

### 導航（v4.1+）
三個儀表板之間用 iframe 方式切換，header 固定不動：
- 點擊 nav link → `switchDashboard(link)` → 載入 iframe（帶 `?embed=1` 參數）
- 子頁面偵測 `?embed=1` → 加 `embed-mode` class → 隱藏自身 header

### 民國年表示
系統用民國年（114 = 2025, 115 = 2026），儲存在 DB 的 `fiscal_year` 欄位也是民國年。

## 常用指令

```bash
# 本地開發
cd public && python -m http.server 8081

# 推送到 main → 自動部署
git push origin claude/<branch>:main

# 查看部署狀態
gh run list --workflow=deploy-pages.yml --limit 3

# 建立 Auth 使用者（需 scripts/.env）
cd scripts && python create_auth_users.py
```

**線上網址**：
- 諮詢分析：https://dennislei-web.github.io/lawyer-dashboard/
- 營運：https://dennislei-web.github.io/lawyer-dashboard/revenue/
- 財務規劃：https://dennislei-web.github.io/lawyer-dashboard/finance/

## 使用者偏好

- **溝通語言**：繁體中文
- **技術偏好**：保持簡單、不過度工程化、避免引入 bundler/框架
- **Git 工作流**：`claude/<branch>` → push 到 `main` → GitHub Pages 自動部署

## 財務規劃頁的資料流（近期新增）

1. **基底**：114 年損益表 Excel → 上傳到「歷史資料」→ 存 `finance_data` (type: historical)
2. **預算計算**：115 年預算 = 114 年月度基底 + `finance_adjustments` 調整項
3. **薪資名冊**：上傳 115 年薪資 Excel → 存 `finance_employees`，掃描所有月份找出在職區間
4. **人事異動偵測**：逐月比對找出 115 年內實際離職/新進，顯示確認表讓使用者勾選套用
5. **實際追蹤**：每月上傳損益表（type: actual）→「實際 vs 預算」tab 顯示差異 + AI 分析

## 注意事項

- **不要 amend commits**：一律建立新 commit
- **敏感資料**：`.env`, `*.xlsx`, `.claude/` 都在 `.gitignore` 忽略
- **薪資表格式差異**：114 和 115 年 Excel 欄位順序可能不同 → 解析時自動偵測 header 而非寫死欄位位置
- **銷貨退回**：在損益表中是減項，subtotal 計算要用 `DEDUCTION_CODES` 處理
- **iframe X-Frame-Options**：`netlify.toml` 有設 DENY，但 GitHub Pages 不受影響；若要切回 Netlify 部署需拿掉該設定
