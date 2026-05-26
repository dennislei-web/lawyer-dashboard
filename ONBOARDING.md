# 同仁 Onboarding — 喆律儀表板 + Claude Code

歡迎加入。這份文件帶你從零設定到可以「改儀表板程式碼」+「跑律師諮詢評估」。預估第一次設定 30-60 分鐘。

> 📖 專案概覽、架構、資料表請看 [`CLAUDE.md`](CLAUDE.md)。本文件只講 **個人環境設定** 和 **協作流程**。

---

## 0. 你會需要的工具

| 工具 | 用途 | 取得方式 |
|---|---|---|
| Git | 版控 | macOS 已內建；Windows 裝 [Git for Windows](https://git-scm.com/download/win) |
| GitHub 帳號 | repo 存取 | [github.com/signup](https://github.com/signup) — 註冊好把帳號丟給 Dennis 加為 collaborator |
| Claude Code | AI 協作 | [claude.com/claude-code](https://claude.com/claude-code) — 需要 Claude Pro / Max 訂閱（Max 比較不會擔心 token 用量） |
| Python 3.10+ | 跑後端腳本 | macOS 用 [pyenv](https://github.com/pyenv/pyenv) 或 [brew](https://brew.sh/)；Windows 從 [python.org](https://www.python.org/downloads/) |
| 一個現代瀏覽器 | 看儀表板 | Chrome / Edge / Safari 都行 |

GitHub CLI（`gh`）不是必要，但能讓 Claude Code 幫你開 PR、看 CI 結果，建議裝：[cli.github.com](https://cli.github.com/)。

---

## 1. 取得 repo 存取權

1. 把你的 GitHub username 給 Dennis
2. 收到 collaborator 邀請信，點進去 accept
3. 在自己電腦上 clone：

```bash
cd ~/projects   # 或你習慣放程式碼的地方
git clone https://github.com/dennislei-web/lawyer-dashboard.git
cd lawyer-dashboard
```

---

## 2. 安裝 Claude Code 與專案 skill

### 2.1 安裝 Claude Code

照 [官方說明](https://docs.claude.com/en/docs/claude-code/getting-started) 裝完，第一次跑會要你登入 Anthropic 帳號。

### 2.2 安裝專案 skill（律師備忘單用）

從 repo 根目錄執行：

```bash
# macOS / Linux
mkdir -p ~/.claude/skills
ln -sf "$(pwd)/skills/lawyer-1on1-brief" ~/.claude/skills/lawyer-1on1-brief
```

Windows 看 [`skills/README.md`](skills/README.md)。

驗證：

```bash
ls -la ~/.claude/skills/lawyer-1on1-brief/SKILL.md
```

有檔案就 OK。Claude Code 之後啟動會自動載入。

### 2.3 在 repo 目錄啟動 Claude Code

```bash
cd ~/projects/lawyer-dashboard
claude
```

Claude 會自動讀到 [`CLAUDE.md`](CLAUDE.md)（專案規範）+ skill 檔，你可以直接下指令。

---

## 3. 設定 Python 環境 + .env

只有要跑後端腳本（同步資料、產備忘單 PDF、批次建使用者）才需要這步。如果你只改前端 HTML 可以跳過。

### 3.1 建 venv 並裝套件

```bash
cd ~/projects/lawyer-dashboard
python3 -m venv .venv
source .venv/bin/activate                 # Windows 是 .venv\Scripts\activate

# 各腳本各自 import 的套件，最常用的：
pip install httpx python-dotenv openpyxl pandas anthropic reportlab
```

> `.venv/` 已在 `.gitignore`，不會進 repo。

### 3.2 設 `scripts/.env`

```bash
cp scripts/.env.example scripts/.env
```

然後用編輯器打開 `scripts/.env` 填值。**`SUPABASE_SERVICE_KEY` 和 `ANTHROPIC_API_KEY` 是機密，永遠不要 commit。** Dennis 會私訊給你。

| 變數 | 怎麼拿 |
|---|---|
| `SUPABASE_URL` | 固定值 `https://zpbkeyhxyykbvownrngf.supabase.co` |
| `SUPABASE_SERVICE_KEY` | 跟 Dennis 拿（Supabase Dashboard → Settings → API → `service_role`）|
| `ANTHROPIC_API_KEY` | 自己去 [console.anthropic.com](https://console.anthropic.com/) 申請，或跟 Dennis 拿事務所共用 key |
| `DEFAULT_PASSWORD` | 只有跑 `create_auth_users.py` 才用到，自己定一個 |

---

## 4. 本地預覽儀表板

```bash
cd public
python3 -m http.server 8081
```

打開 http://localhost:8081/ 看諮詢分析儀表板，http://localhost:8081/revenue/ 看營運儀表板，依此類推。

登入用你個人在系統內的 Supabase Auth 帳號（沒帳號跟 Dennis 開）。

---

## 5. Git 工作流

### 分支命名

`claude/<簡短主題>`，例如：

- `claude/consultation-signing-trend-fix`
- `claude/finance-budget-2027-page`

### Push & 部署

repo `main` branch 上了 **branch protection**：禁止 force-push、禁止刪 main。**直接 push 到 main 仍然可以**（會自動觸發 GitHub Actions 部署到 Pages），但建議走以下流程：

#### 流程 A：開 PR 給 Dennis review（建議）

```bash
git checkout -b claude/my-feature
# ... 改檔案 ...
git add -A
git commit -m "feat(consultation): xxx"
git push -u origin claude/my-feature
gh pr create                  # 或在 GitHub 網頁開
```

Dennis 看過 approve 後，由他 merge 到 main。

#### 流程 B：信任你的小修改可以直接上

```bash
git push origin claude/my-feature:main
```

> ⚠️ 任何會動到金錢/薪資/實際營收的修改，**一律走流程 A**。

### 部署觀察

```bash
gh run list --workflow=deploy-pages.yml --limit 3
```

線上網址（main push 後 1-2 分鐘生效）：

- 諮詢分析：https://dennislei-web.github.io/lawyer-dashboard/
- 營運：https://dennislei-web.github.io/lawyer-dashboard/revenue/
- 財務規劃：https://dennislei-web.github.io/lawyer-dashboard/finance/

---

## 6. 兩個常見任務的操作指南

### 6.1 改儀表板程式碼

1. 在 repo 目錄打開 Claude Code：`claude`
2. 直接描述需求，例如：
   - 「諮詢分析的『未成案追蹤』tab 多加一個篩選器，可以依案型過濾」
   - 「營運儀表板的合署律師統計表，加上每位律師的客單價中位數欄位」
3. Claude 會讀 `CLAUDE.md` 和相關 `index.html` 後動手
4. 改完讓 Claude 起本地 server 自己驗，或你手動開 http://localhost:8081/ 確認
5. Commit + push

### 6.2 產律師 1-on-1 備忘單

1. `cd ~/projects/lawyer-dashboard && claude`
2. 對 Claude 說：「**產 OOO 律師的 1-on-1 備忘單**」（OOO 是律師全名）
3. Claude 會自動：
   - 檢查該律師會議記錄筆數
   - 依數量決定走 inline 還是 API 路徑（< 50 筆通常 inline）
   - 從 Supabase 抽案件 + 跑 LLM 歸因
   - 產出 A4 PDF 到 `scripts/briefs/{律師名}_brief.pdf`
4. PDF 不會進 git（`scripts/briefs/` 已在 `.gitignore`）

> 如果你的訂閱沒有 inline 模式的 token 額度，或律師案件超過 150 筆，要用 API 模式 — 需要 `ANTHROPIC_API_KEY`。

---

## 7. 安全 & 注意事項

- **絕對不要 commit `scripts/.env`** — 已被 `.gitignore` 擋住，但 `git add -A` 前還是再確認一下 `git status`
- **薪資、員工個資 Excel 檔不要進 repo** — `*.xlsx` 已 ignore
- **修改前端 HTML 時不會碰到資料庫** — 但如果你改了 SQL migration 或 Python 腳本，**先跟 Dennis 確認**
- **不要 amend 別人的 commit** — 一律建新 commit
- **Supabase RLS** — 前端用 anon key 受 RLS 限制，admin 才能寫。Python 腳本用 service key 繞過 RLS，所以**腳本要特別小心，寫入前先想清楚會影響哪些 row**

---

## 8. 卡關時怎麼辦

1. 先問 Claude Code（在 repo 目錄問，它有 `CLAUDE.md` 的 context）
2. 看 git history 找最近類似改動：`git log --oneline -20`
3. 看 [`CLAUDE.md`](CLAUDE.md) 的「核心慣例」「資料表」「財務規劃頁的資料流」段落
4. 真的卡住才問 Dennis — 把錯誤訊息、你跑的指令、預期 vs 實際結果整理好一起貼
