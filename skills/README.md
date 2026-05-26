# Claude Code Skills

這個資料夾放專案專屬的 Claude Code skill。Skill 是給 Claude 用的「操作手冊」，當你下達特定指令（如「產 OOO 律師備忘單」），Claude 會自動載入對應 SKILL.md 並按裡面的流程做事。

## 已有的 skill

| 名稱 | 用途 |
|---|---|
| `lawyer-1on1-brief` | 為律師產生 1-on-1 會議備忘單 PDF（從 Supabase 抽案件、跑 LLM 歸因分析、輸出多頁 A4 報告）|

## 安裝（每位同仁第一次拿到 repo 都要做一次）

Claude Code 預設只會載入 `~/.claude/skills/` 底下的 skill。把 repo 內的 skill 用 symlink 連過去，之後 `git pull` 就會自動同步更新。

### macOS / Linux

```bash
# 從 repo 根目錄執行
mkdir -p ~/.claude/skills
ln -sf "$(pwd)/skills/lawyer-1on1-brief" ~/.claude/skills/lawyer-1on1-brief

# 驗證
ls -la ~/.claude/skills/lawyer-1on1-brief
```

### Windows（PowerShell，需以系統管理員開啟）

```powershell
# 從 repo 根目錄執行
New-Item -ItemType Directory -Force -Path "$HOME\.claude\skills"
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\lawyer-1on1-brief" -Target "$PWD\skills\lawyer-1on1-brief"
```

不能用 symlink 的話，直接 `cp -r skills/lawyer-1on1-brief ~/.claude/skills/`（缺點：repo 更新時要重新 copy）。

## 驗證安裝成功

打開 Claude Code，在 repo 目錄輸入：

```
產 雷皓明 律師的 1-on-1 備忘單
```

Claude 應該會自動觸發 `lawyer-1on1-brief` skill 並開始問前置條件（案件數、是否要先 sync DB 等）。如果沒觸發，檢查 `~/.claude/skills/lawyer-1on1-brief/SKILL.md` 是否存在。

## 我要新增/修改 skill

直接編輯 `skills/<name>/SKILL.md`，commit + push。其他同仁 `git pull` 後因為 symlink 會自動拿到最新版。

SKILL.md 結構：

```markdown
---
name: <kebab-case-name>
description: <一句話：什麼情境會觸發這個 skill。要具體，這是 Claude 判斷要不要載入的依據>
tools: Read, Edit, Write, Bash, Grep, Glob
---

# Skill 主體（給 Claude 看的操作手冊）
...
```
