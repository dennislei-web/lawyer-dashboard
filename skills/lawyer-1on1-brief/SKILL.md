---
name: lawyer-1on1-brief
description: 為喆律法律事務所律師產生 1-on-1 會議備忘單 PDF。從 Supabase 抽案件資料、對會議記錄跑 LLM 歸因分析、輸出多頁 A4 報告（含 narrative、案型趨勢、AI 行為歸因配當事人名/案號、簽約滯後分析、具可量化驗收指標的後續行動）。使用情境：使用者要求「產 OOO 律師的備忘單」、「做 OOO 1-on-1」、「幫 OOO 做諮詢成案分析」。
tools: Read, Edit, Write, Bash, Grep, Glob
---

# 律師 1-on-1 備忘單生成

為主管準備與律師的 1-on-1 會議的 A4 PDF 備忘單。資料來源：Supabase `consultation_cases` + `revenue_records`；AI 歸因用 Claude Sonnet 4.5（API 路線）或 Claude Opus 4.7（對話中 inline）。

## 核心設計哲學（**先讀這段再動手**）

1. **效益值（收款/諮詢數）是首要指標，成案率次要** — 客單價上升的同時成案率下滑，是**策略選擇**（選擇接高價案），不是問題。不要把「回升成案率」當 action target。
2. **案例引用必帶 `當事人名 + 案號`** — 律師光看 case_date + case_type 無法立刻 recall，加上名字可以
3. **量化驗收指標放最後** — 每個 action 必須有「下月怎麼看進展」的明確數字
4. **追蹤機制要 3 層節奏**：每週自檢（律師）+ 期中 AI 重分析（2 週）+ 下次完整 brief（4 週）
5. **追蹤機制必須動態產生** — `build_brief_pdf.py` 的追蹤機制依律師實際 actions / 行為斷點 / 指標組出，絕不能硬寫特定律師的數字（避免「跟琬琪的一模一樣」）
6. **登錄偏誤的核心處理（提案 B）** — 律師只對**已成案案件**補填具體案件內容，未成案幾乎都歸「(未指定案件內容)」。因此：
   - **絕對不用「案件內容 × 成案率」做強弱項比較** — 分母被抽掉，成案率都會被高估到 > 80%，是 artifact
   - **絕對不用「案件內容 × 效益值」** — 效益值 = collected/n_consult，但在登錄偏誤下 n_consult ≈ n_signed，效益值 ≈ 客單價，標籤誤導
   - **可以用**：整體成案率（分母全部）、諮詢型態成案率（不受偏誤）、已成案客單價 vs 全所基準（分母可靠）、AI 歸因
   - PDF 要有「近 3 月成案率拆解」+ 偏誤警告框明確揭露這個現象
7. **強弱項一律改用「已成案客單價 vs 全所基準」** — `prep.strengths` / `prep.weaknesses` 的排序依據從 `sign_rate_gap` 改為 `unit_gap_pct`；條件 `my_signed >= 5` 且排除「(未指定案件內容)」；顯示時明確標註「※ 僅看已成案案件」
8. **兩個維度分開分析** — case_type 欄位同時存諮詢型態（現場/視訊/電話）+ 案件內容（民事一審/支付命令…）。用 `extract_consult_method` 和 `extract_case_content` 分別抽出，絕不用舊的 `split(",")[0]` 邏輯（會把「現場諮詢, 支付命令」誤歸「現場」）
9. **全中文 PDF** — 使用者可見內容一律中文，避免 LLM / SOP / ROI / cross-sell / momentum 等英文術語；「pp」（percentage point）一律改「%」（即使統計上是 pp）
10. **Action 必須個人化** — 不能多位律師產一樣的 action copy。解法：`build_brief_pdf.py` 的 `generate_personalized_actions()` 餵該律師 21 筆個案分析 + 強弱項 + 趨勢 + 同所別 baseline 讓 LLM 產 3-4 個 action（每個必帶 1-3 筆真實案件引用）。rule-based 保留做 fallback
11. **趨勢資料必備** — 強弱項案型要分「近一季 vs 更早」兩段，展示變好/變差/近一季無已簽。小樣本（n<3）要標 ⚠ 避免誤判
12. **同所別 baseline 更公平** — 全所 baseline 會混入合署/司法官合署（客單價差 $30K+）。強弱項和 metrics 都要並列「全所 / 同所別」兩種 baseline，LLM action 優先引同所別
13. **律師 per-type 平均客單價分位（2026-05 新增）** — 用「律師個人在該案型的平均客單」當基本單位，求所有合格律師（已簽 ≥ 5）的 P25/P50/P75，不是案件級分位。每個 strengths/weaknesses 帶 `firm_unit_p25/p50/p75/firm_peer_lawyer_n/firm_peer_position`（值如「<P25」「P25-P50」「P50-P75」「≥P75」）。`<P25` 是嚴重訊號 — 律師在全所同案型律師中落最低 25%。LLM action 必須具體寫出「全所 N 位律師中你 <P25、P50 是 X、P75 是 Y」而不是抽象 gap %
14. **同年度比較 yearly_compare（2026-05 新增，驗偽年資 confounder）** — 主管常會反問「客單低是不是因為律師年資久、過往報價就低？」。用「上一個完整年 + 當前年 × 我 vs 全所同年度」隔離這個 confounder：若 ratio_pct（律師 / 全所同年）每年都 < 80，年資解釋不成立；若 ratio_pct **逐年下降**，代表「事務所漲了但律師沒跟上」— 這是比「客單慣性偏低」更具行動性的論點，metric 要改用「跟上 firm_avg 同年度」而非歷史 P50。**反證手法**：若該律師有任一案型同年度 ratio_pct ≥ 150%（如王郁萱撰寫書狀 165%），就可以 falsify「能力不夠 / 報價慣性全面性偏低」的論點 — 律師敢報高價，只是對特定案型有低報習慣
15. **A/B 程序分類與 A 密度（2026-05-22 新增）** — 把「案件內容」二分為 A（完整訴訟程序：民/家/刑各審、強執、保護令、家事/勞動調解、改定監護、收養、確認親子、假扣押、聲請限定繼承、包套等）vs B（部分程序：律師函、存證信函、各類協議書、代協商、陪同調解、撰寫書狀、支付命令、本票裁定、證人/警詢/陪偵/閱卷/律見、公證、代筆遺囑、法律顧問、契約等）。Tag 清單見 [public/consultation/index.html:4448-4481](public/consultation/index.html#L4448) 與本 SKILL「A/B 程序分類與 A 密度分析」章節。**A 密度 = 簽成 A 件數 / 總諮詢數**（不是 / 成案數），全所平均 22.8%。實證：A 密度 vs 每場諮詢營收相關係數 **+0.66**；成案率 vs 每場諮詢營收 **只 +0.15** — **管理上絕不可單看成案率**（廖懿涵成案率 56.4% 全所第二高、但 A 密度只 19.4%、每場諮詢營收 2.42 萬，僅雷皓明 49% 水平）。A 密度同時受「諮詢識別→提案完整訴訟程序」+「把客戶簽下高價 A 案」兩種能力影響，是律師端綜合產出指標。**注意：A 密度的分子（A 件數）來自「成案後填寫的 case_type」，這是允許的偏誤** — 未成案 94.8% 沒填具體 A/B tag，但因為**分母用「總諮詢」而非「總已分類諮詢」**，這個指標不會被登錄偏誤汙染。
16. **A 次類別解構（2026-05-22 新增）** — A 案內部要再細拆為六類，單價差距大：包套 13 萬、家事/民事/刑事 ~10 萬、調解 8 萬、執行救濟僅 6 萬。每位律師有專科輪廓需在 brief 中描述（雷皓明均衡多核 + 包套 16%、孫少輔純刑事 100%、李昭萱重家事 60%、林桑羽零家事）。**包套是高毛利核武**（單價 13 萬、含 P75 15 萬），但極度集中（雷皓明 86 件、其他律師多在個位數）— brief 對「無包套產品」的律師應在 action 中提推廣包套的具體案件目標。執行救濟單價低（中位 5 萬），對「執行救濟比例偏高」的律師要點出此為低毛利區。
17. **案件級單價分位（2026-05-22 新增）** — 第 13 點的 `firm_unit_p25/p50/p75` 是「律師間比較」（用每位律師的平均當基本單位求分位）；本點補充「**律師個人在該案型內所有案件的價格分散度**」（案件級分位）。對單一律師單一案型，求 P25/P50/P75/P90/max — 若分布被壓在 8-9 萬區間（P75 ≈ 全所案件級 P50），代表此律師整體沒有「敢開高價」的案件，比平均偏低更鐵證。範例：雷皓明家事一審 285 件 P25=10、P50=12、P75=15 萬；廖懿涵 62 件 P25=8、P50=8、P75=9.2 萬 — **廖懿涵 77% (48/62) 的家事一審單價低於雷皓明 P25**。當「平均偏低 X%」太抽象時，用案件級分位對照（「你 P75 = 對手 P25」）是最具說服力的 action 證據，建議在客單低的弱項 action 中加入此對照。

## 觸發關鍵字

- 「產 OOO 律師 1-on-1 備忘單 / brief」
- 「幫 OOO 做諮詢效益分析」
- 「做 OOO 的 1-on-1」

## 資料前置條件

檢查律師是否符合生成備忘單的最低門檻：

```python
# 查會議記錄筆數 — < 3 筆建議不跑
cd /c/projects/lawyer-dashboard/scripts && python -c "
import os, io, sys, httpx
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv('.env', override=True)
URL=os.environ['SUPABASE_URL']; KEY=os.environ['SUPABASE_SERVICE_KEY']
HDR={'apikey':KEY,'Authorization':f'Bearer {KEY}'}
# Replace NAME
name = '洪琬琪'
r=httpx.get(f'{URL}/rest/v1/lawyers', params={'select':'id,name','name':f'eq.{name}'}, headers=HDR)
lw = r.json()[0]
r=httpx.get(f'{URL}/rest/v1/consultation_cases',
    params={'select':'id,meeting_record,llm_analysis','lawyer_id':f'eq.{lw[\"id\"]}'}, headers=HDR)
cases = r.json()
with_mr = sum(1 for c in cases if c.get('meeting_record') and len(c['meeting_record'])>=50)
done_llm = sum(1 for c in cases if c.get('llm_analysis'))
print(f'{name}: 總案 {len(cases)} · 有會議記錄 {with_mr} · 已 LLM 分析 {done_llm}')
"
```

**決策規則**（Claude Opus 4.7 1M context / Max 20x 已啟用）：

| 案件數 | 建議路徑 | 需要先做的事 |
|---|---|---|
| `< 3` | 資料不足 | 先請律師補會議記錄 |
| `3 ~ 50` | Inline（我直接分析）| 估算 context 後直接開跑，不用先問 |
| `50 ~ 150` | **先問使用者** | 給 context + API 成本試算，使用者決定路徑 |
| `150+` | API 為主 | 避免吃爆 context（即便 1M 也建議切 API 降成本）|

## 跑大量案件的操作手冊

**核心資訊**：每筆案件 ≈ **10-12K tokens** 進 context（會議記錄 3K 字 + 逐字稿 7-10K 字 + 我的分析輸出 800 tokens）。

### 預估 context 用量（開跑前必做）

```
已用 context = (當前 session 長度估算)
每筆成本   ≈ 11K tokens
N 筆總耗   ≈ N × 11K

安全閾值  ：總量 < 1M × 70% = 700K tokens（留 30% 給後續對話）
觸發警告  ：總量 > 900K（接近 1M 上限）
```

**檢查公式**：`(新案件數 × 11) + 目前已用 K tokens ≤ 700K` → 安全
反之要**另開 session** 或**改 API**。

### 路徑 A：API 腳本（推薦 50+ 筆）

```bash
cd /c/projects/lawyer-dashboard/scripts
python llm_analyze_cases.py --name "律師姓名"
```

**優點**：完全不吃 context、可背景跑、有 rate limit + retry
**成本**：每筆 ~$0.04 USD（30 筆約 $1.2）
**餘額檢查**：登入 `console.anthropic.com` 看 credit balance
**時長**：受 10k tokens/min rate limit 影響，30 筆約 15-30 分鐘

### 路徑 B：Inline（我在對話中逐筆分析）

**適合**：API 沒餘額、案件不多、這個 session 剛開始

**操作**：
1. 我讀 `briefs/raw_data/{律師名}_prep.json` 的 `cases_with_meeting_record`
2. 每次 batch 讀 3-5 筆（避免單次塞太多），寫出分析 JSON
3. 用 Python 直接 `httpx.PATCH` 寫回 `consultation_cases.llm_analysis`
4. 最後合併寫入 `{律師名}_llm.json`

**批次策略**：
- 3 筆一批 → 每批 ~35K tokens → 安全、可重複
- 跑完一批回報進度 → 使用者決定是否繼續
- 若中途 context 吃緊，提早停止，改走 A 路徑

### 路徑 C：混合（50-150 筆首選）

前 10 筆用我 inline（快速看品質、不花錢），剩下交給 API 跑。
**理由**：確認 prompt 沒問題 + 初步看 pattern，再讓 API 全量處理。

## 遇到 50+ 筆時的**必問提示**

使用者要求為有 50+ 筆會議記錄的律師產備忘單時，**先停下來問**：

```
{律師名} 有 {N} 筆會議記錄。三種跑法：

A. API 腳本（$${N*0.04:.1f})，不吃 context，~{N//2}-{N} 分鐘
B. 我 inline 跑（0 成本，吃 ~{N*11}K tokens context）
C. 混合：我先跑 10 筆看品質，剩 {N-10} 筆交給 API

建議：{根據 context 和 API 餘額推薦}。你決定？
```

## 標準三步流程

### Step 1：抽資料（唯讀，不花錢）

```bash
cd /c/projects/lawyer-dashboard/scripts
python prep_1on1_data.py --name "律師姓名"
```

產出 `briefs/raw_data/{律師名}_prep.json`，含：
- `overall`：
  - 律師自己：`consult_count / signed_count / sign_rate / collected / avg_collected / consult_eff`
  - 全所 baseline：`firm_sign_rate / firm_eff / firm_avg_unit`
  - **同所別 baseline**（2026-04 新增、不含本人）：`office / office_peer_count / office_sign_rate / office_eff / office_avg_unit`
- `recent3_months` / `prev3_months` / `recent_agg` / `prev_agg` / `period_delta`：近 3 月 vs 前 3 月彙總
- `monthly_trend`：近 12 個月月資料
- `strengths` / `weaknesses`：**已成案客單價 vs baseline**，欄位：
  - 基本：`case_type`、`n`、`my_signed`、`my_avg_collected`
  - 全所 baseline：`baseline_avg_collected`、`unit_gap`、`unit_gap_pct`
  - **同所別 baseline**（2026-04 新增）：`office_baseline_avg_collected`、`office_baseline_n`、`office_unit_gap`、`office_unit_gap_pct`（同所別該 case_type n<5 時為 None）
  - **趨勢**（2026-04 新增）：`trend.{recent_n, recent_signed, recent_avg_collected, recent_sign_rate, earlier_n, earlier_signed, earlier_avg_collected, earlier_sign_rate, unit_delta_pct, trend_label, small_sample}`
  - **律師 per-type 平均客單分位**（2026-05 新增）：`firm_unit_p25/p50/p75`、`firm_peer_lawyer_n`、`firm_peer_position`（值「<P25」「P25-P50」「P50-P75」「≥P75」）；同所別版 `office_unit_p25/p50/p75/office_peer_lawyer_n/office_peer_position`（同所合格律師 < 5 為 None）
  - **同年度比較**（2026-05 新增，驗偽年資 confounder）：`yearly_compare: [{year, my_signed, my_avg_collected, firm_signed_n, firm_avg_collected, ratio_pct}]`，含上一個完整年 + 當前年；`ratio_pct = 律師 / 全所同年度 × 100`（100 = 同水準）
  - 排序依據：`unit_gap_pct`；條件 `signed >= 5` 且排除「(未指定案件內容)」
- `consult_method_stats`：諮詢型態維度（現場/視訊/電話/(未標記)）的 n、成案率、客單價 vs 全所基準
  - **律師 per-method 分位**（2026-05 新增）：`firm_unit_p25/p50/p75`、`firm_eff_p25/p50/p75`、`firm_unit_position`、`firm_eff_position`、`my_avg_collected`
- `cases_with_meeting_record`：給 LLM 分析用

**key 變更說明**：
- 舊版 `strengths` / `weaknesses` 排序用的是 `gap`（成案率差）— **提案 B 已移除，改用 `unit_gap_pct`**
- 舊版有 `my_consult_eff` / `baseline_consult_eff` — 保留但不再用（因為是 artifact）
- 新增 `my_avg_collected` = `collected_of_type / signed_of_type`（只算有簽的平均收款，可靠）
- **2026-04 新增** `office_*` baseline 與 `trend`（見後文「同所別 baseline」與「近一季 vs 更早 趨勢」章節）

### Step 2：LLM 歸因分析

**A. API 路線（律師案件多時）**：

```bash
python llm_analyze_cases.py --name "律師姓名"
```

- 模型：Claude Sonnet 4.5
- Rate limit：10k input tokens/min（腳本有 throttle + retry）
- 每筆成本約 $0.04（會議記錄平均 3k 字 + transcript 10k 字）
- 結果寫入 DB `consultation_cases.llm_analysis` JSONB + 本地 `{律師名}_llm.json`（merge 模式不會覆蓋）

**⚠️ 已知問題：`llm_analyze_cases.py` 會 hang**（實測 21 筆跑到第 8 筆整個腳本卡死 2+ 小時，即便 Python process alive）。根因不明但通常跟 SDK 某次 API retry 進入死迴圈有關。

**補救：`llm_analyze_resume.py`**（timeout=90s、max_retries=2、per-case try/except）

```bash
python llm_analyze_resume.py "律師姓名"
```

特性：
- 自動 skip DB 已分析的案件（不用 `--force`）
- 單筆 timeout 卡死會直接跳下一筆而非卡整批
- 輸出與 `llm_analyze_cases.py` 相容（寫 DB + 同結構）
- **預設路徑**：第一次嘗試用 `llm_analyze_cases.py`；若半小時沒進度（`ls -la` 看 output 檔 mtime）就 kill 換 `llm_analyze_resume.py`。或直接用 resume 版也 OK。

**完成後需同步 DB → JSON**（因為 resume 腳本只寫 DB）：見下方「若 DB 有記錄但 JSON 沒有」的 snippet。

**若 DB 有記錄但 JSON 沒有**：
```python
# sync DB → JSON
import json, httpx, os, pathlib
from dotenv import load_dotenv
load_dotenv('.env', override=True)
URL=os.environ['SUPABASE_URL']; KEY=os.environ['SUPABASE_SERVICE_KEY']
HDR={'apikey':KEY,'Authorization':f'Bearer {KEY}'}
LID='lawyer-uuid-here'
r=httpx.get(f'{URL}/rest/v1/consultation_cases',
    params={'select':'id,case_date,case_type,is_signed,collected,llm_analysis',
            'lawyer_id':f'eq.{LID}','llm_analysis':'not.is.null','order':'case_date.desc'},
    headers=HDR, timeout=30)
synced = [{'case_id':x['id'],'case_date':x['case_date'],'case_type':x['case_type'],
           'is_signed':x['is_signed'],'collected':x['collected'],'analysis':x['llm_analysis']} for x in r.json()]
pathlib.Path(rf'briefs/raw_data/{name}_llm.json').write_text(
    json.dumps(synced, ensure_ascii=False, indent=2), encoding='utf-8')
```

**B. Inline 路線（案件少、沒餘額）**：

我（Claude Code）直接讀 prep.json 裡的 `cases_with_meeting_record`，逐筆用 `PROMPT_TEMPLATE`（見 `scripts/llm_analyze_cases.py` line 32）產出 JSON 寫回檔案和 DB。**省錢但吃 session context，15 筆以內才適合**。

### Step 3：產 PDF

```bash
python build_brief_pdf.py --name "律師姓名"
```

- 自動從 DB 拉所有案件做案型趨勢分析
- 自動配對 `revenue_records` 算簽約滯後分布
- **LLM 個人化 action**（Claude Sonnet 4.5）— 依該律師 21 筆個案分析 + 強弱項 + 趨勢 + 同所別 baseline 產 3-4 個 action
- 失敗時自動退回 rule-based 模板（保障不會壞掉）
- 輸出 `briefs/{律師名}_brief.pdf`（6 頁 A4）+ 同名 HTML（debug 用）

CLI 旗標：
- `--html-only`：只產 HTML 不轉 PDF
- `--no-llm-actions`：強制用 rule-based（不呼叫 LLM）— 緊急情況或預算考量用

## PDF 內容結構（提案 B：登錄偏誤處理後版本）

**設計原則**：律師只對已成案案件補填具體案件內容 → 用「案件內容 × 成案率」做比較是 artifact。本設計把分析分成兩層：

**第一層（最可靠）**：不受登錄偏誤影響的維度
- 整體 4 卡片（分母是全部案件，可靠）
- **近 3 月成案率拆解**（兩維度並列 + 偏誤警告框）— 揭露偏誤
- **諮詢型態表現**（現場/視訊/電話 × 成案率 × 客單價 vs 全所）— 升級為主角
- 未指定案件內容明細
- 簽約滯後分析
- AI 歸因失敗原因 + 行為斷點

**第二層（已成案分析，明確標註）**：
- **已成案客單價 · 強項/弱項**（取代舊的「案件內容成案率」強弱項）— 以「我 vs 全所同類別基準」的客單價 gap% 排序
- **已成案客單價趨勢表**（取代舊 trend_table）— 只看件數和客單價，刪除率 / 效益欄

**明確刪除**：
- 「案型深度分析」黃框敘事（trend_narrative）— 討論成案率/效益變動都是 artifact
- 「強弱項案件內容」用成案率排序（舊版）
- trend_table 的「率Δ」「效益」欄

| 頁 | 區塊 |
|---|---|
| 1 | Header + 整體敘事 + 整體 metrics（4 卡）|
| 2 | 近 3 月成案率拆解（近 N 筆 · 偏誤警告）+ **月度趨勢表（揭示轉折點）** + 諮詢型態長期表現（全部歷史 vs 全所基準）+ 資料補填漏洞表（若有）|
| 3 | 簽約滯後分析 + 已成案客單價強/弱項 + 已成案客單價趨勢 |
| 4 | 做得好的 4 件事 + 下次可更好的 3 件事（第 1 張）|
| 5 | 下次可更好的 3 件事（第 2、3 張）+ 失敗原因 + 行為斷點 |
| 6 | 會議討論問題 + 後續行動重點 + 追蹤機制 |

### 各 section 規則

- **近 3 月成案率拆解**：用 `all_cases + recent3_months cutoff` 算（**僅近 3 月樣本**）。兩個維度表（案件內容、諮詢型態）並列，「(未指定案件內容)」列標黃底紅字。偏誤警告框解釋為什麼本 PDF 不用「案件內容 × 成案率」做比較。標題必須含「僅 N 筆近期案件」字樣避免跟下方整體表混淆。
- **諮詢型態長期表現**：用 `prep.consult_method_stats`（**律師全部歷史案件 vs 全所基準**）。差距欄一律用 `%`，不要用 `pp`。標題必須含「全部 N 筆歷史案件」字樣，並加說明「統計範圍：律師全部歷史案件，和上方『近 3 月拆解』的數字不同」— 避免使用者把兩個表的成案率看成矛盾數字。

- **月度趨勢表（近 12 個月）**：用 `prep.monthly_trend`。六欄：月份 · 諮詢 · 簽 · 成案率 · 收款 · 效益/人。自動偵測**結構性轉折點**並用紅底標出該列。演算法：
  - **只在近 6 個月內**挑候選（避免挑到久遠歷史中的單月雜訊，例如淡季 7 月效益很低但不代表結構問題）
  - 條件：月效益相對前月下滑 ≥ 30% 且前月效益 ≥ 20,000
  - **結構性檢查**：後續月份沒回到前月 80% 水準才算（若有回升就是單月雜訊）
  - 若多個月都符合，**取最新的**
  - 找到後自動產生一行敘事：「⚠️ YYYY-MM 是效益下滑的轉折點（跌 X%）—— 會議中可以問律師『YYYY-MM 有什麼不一樣嗎？』」

此表的價值：解答「為什麼儀表板 YTD 數字跟 PDF 近 3 月不同」—— 儀表板是 2026 年至今（含 1 月）、PDF 近 3 月是 rolling 3 個月（可能不含 1 月）。真正的下滑訊號藏在**月度轉折**，不是「近 3 月平均」。

### 時間範圍標註規則（強制）

**所有出現比較數字的欄位都必須清楚標示時間範圍** — 不能只寫「全所」「同所別」「近一季」「更早」這種無區間標籤。`build_brief_pdf.py` 已有區間 label 變數可用：

| 變數 | 例值 | 用途 |
|---|---|---|
| `recent3_label` | `2026-02~2026-04` | 近 3 月（QoQ 用） |
| `prev3_label` | `2025-11~2026-01` | 前 3 月（QoQ 用） |
| `recent6_label` | `2025-11~2026-04` | 近 6 月（已成案客單價趨勢用） |
| `earlier_label` | `2020-10~2025-10` | 更早（已成案客單價趨勢、`_fmt_trend` 用） |
| `data_snapshot` | `2020-10 ~ 2026-04` | 律師整體 + baseline 的全部歷史範圍 |

**強制規則**：
- 4 卡片 baseline 必標「（全部歷史）」+ `data_snapshot` 期間
- QoQ 卡片要標清楚是 rolling 6 月切兩半（不是 YoY、不是 vs 全部歷史平均），列出 `recent3_label vs prev3_label`
- 諮詢型態長期表現、強弱項客單價、客單價趨勢、`_fmt_trend` 小字 — section 標題或副標必須含區間
- 加新 section 時務必沿用此規則
- 律師看到「全所 47.3%」會誤以為是當月、近 3 月或當季；沒區間 = 對話論述失準

**林桑羽的案例**：
- 「近 3 月拆解」現場 33%（6/18）vs「長期表現」現場 50%（196/392）— 範圍不同所以數字不同
- 若兩表都只寫「現場」不說範圍，使用者會以為系統計算錯誤
- 範圍差異大的案例要在 narrative 或註解主動說明（例如「近 3 月成案率掉到 33%，比長期 50% 顯著下滑」）
- **資料補填漏洞表**（原「未指定案件內容明細」的精簡版）：只顯示**「已簽約 + case_type 只填諮詢方式」**的案件（律師忘了補具體案件內容）。用意是觸發律師回補資料，讓下次統計更準。未成案的未指定案件不列（細節價值低、失敗模式已被 AI 歸因 section 覆蓋）。如果沒這種案件就整個 section 消失。
- **已成案客單價強/弱項**：資料來源 `prep.strengths` / `prep.weaknesses`。`prep` Step 5 **改用客單價 gap 排序**（非成案率 gap）。條件：`signed >= 5` 且 `case_type != "(未指定案件內容)"`。欄位：`my_avg_collected`、`baseline_avg_collected`、`unit_gap`、`unit_gap_pct`、`my_signed`。顯示時明確標註「※ 僅看已成案案件」。
- **已成案客單價趨勢表**：只顯示件數 / 客單價 / 件數Δ / 客單價Δ。刪除「率」「效益」欄。頂部警告：「因登錄偏誤...只看已成案案件的件數與客單價，不看成案率或效益值」。

## 兩個維度分開分析（case_type 結構）

`case_type` 欄位同時存兩個維度，必須分開處理：

| 維度 | 範例值 | 函數 |
|---|---|---|
| **諮詢型態** | 現場 / 視訊 / 電話 / (未標記) | `extract_consult_method(t)` |
| **案件內容** | 支付命令、民事一審、刑事偵查程序… / (未指定案件內容) | `extract_case_content(t)` |

`"現場諮詢, 支付命令"` → 型態=`現場`, 內容=`支付命令`
`"現場諮詢"` → 型態=`現場`, 內容=`(未指定案件內容)`
`"民事一審"` → 型態=`(未標記)`, 內容=`民事一審`

**不要用舊邏輯**（`split(",")[0]` 取第一項）— 會把「現場諮詢, 支付命令」誤歸為「現場」。`clean_case_type` 保留為 `extract_case_content` 的別名（向後相容）。

## Action Items 產生邏輯（LLM 個人化，2026-04 改版）

### 設計原則

**問題背景**：rule-based 版本會讓多位律師產出幾乎一模一樣的 action（例如三位都有「48 小時回訪 SOP」+ 完全一樣的 copy），因為只用 top 失敗原因標籤填 template。使用者看過會覺得「怎麼每個人講一樣的話」。

**解法**：改用 LLM 讀該律師所有 21 筆個案分析 + 強弱項 + 趨勢 + 同所別 baseline，直接產 3-4 個個人化 action。浪費掉的 LLM 輸出（`missed_opportunities`、`improvement_for_lawyer`、`transferable_pattern`、`reason_evidence`）終於被用上。

### 技術實作

`build_brief_pdf.py` 的 `generate_personalized_actions(...)` 函式：

- 模型：Claude Sonnet 4.5，`max_tokens=6000`、`max_retries=10`、`timeout=180`（**這三個值試過都不能再降**）
- 輸入 context（JSON）：律師整體 metrics、`strengths_case_types`/`weaknesses_case_types`（含 firm baseline + office baseline + trend + small_sample）、`top_failure_reasons`、`behavior_breakpoints`、`lag_stats`、每筆案件摘要（含當事人名、案號、LLM 4 個輸出欄位）
- 輸出：`{actions: [{title, why, how[], metric, cited_cases[]}]}`
- Rule-based 保留當 fallback：`--no-llm-actions` 或 LLM 失敗時觸發

### Prompt 指引摘要（完整見 `build_brief_pdf.py` 的 `user_prompt`）

1. 每個 action 必帶 1-3 筆具體案件引用（「2026-03-30 廖怡雯案」格式）
2. 根據真實數據選題（弱項客單低→案型策略；強項表現好→cross-sell；失敗原因拆開不合併）
3. **善用雙 baseline + 分位 + 同年度比較**（2026-05 改寫）：
   - 比較時優先引同所別，但全所要提以呈現相對位置
   - `firm_position == "<P25"` 是嚴重訊號 — why 必須寫「全所 N 位律師中你 <P25、P50 是 X、P75 是 Y」
   - **`yearly_compare.ratio_pct` 用來證偽年資 confounder**：若上年 + 本年 ratio_pct 都 < 80，年資解釋不成立；若 ratio_pct 逐年下降，代表「事務所漲了但律師沒跟上」
   - 永遠優先引同年度數字（「2026 年律師函全所 40K、你 0 件 / 2025 為 14.8K」勝過「歷史平均 18.8K vs P50 30K」）
4. **善用趨勢資料**：變差的強項最緊急、變好的弱項「延續做對的事」、近一季無已簽是案源流失警訊、`small_sample=true` 要謹慎
5. 嚴禁通用 SOP 模板（「三問 SOP」「48h 回訪」「結尾三問」）除非有真實案件證據
   - 禁用詞清單：跨律師通用模板名 — 寫之前先掃 `cases[*].reason_specific` / `missed_opportunities`，≥ 2 筆獨立案件提到才能用
6. **至少有 1 個 action 必須以「同所別 / 全所分位差」作為立論主軸**（2026-05 新增）
7. how ≥ 3 條具體做法含話術或工具
8. **metric 目標值優先順序**（2026-05 改寫）：
   - 優先：跟上 `firm_avg` 當年度（用 `yearly_compare[本年].firm_avg`）— 最 actionable
   - 其次：回到 `firm_p50`
   - 再次：自身趨勢倒回（例：回到 44K）
9. 避免重複，3-4 個 action 涵蓋不同面向；任何兩個 action 的 title 不可使用同一個動詞模板
10. 效益值與客單價優先，成案率次要

### JSON 截斷救援

LLM 回 4000+ tokens 常見（`洪琬琪`、`林桑羽` 都曾觸發）。`_try_recover_actions_json()` 切到最後一個完整 action object 的 `}` 後補 `]}` 恢復。

### Rule-based Fallback（僅 LLM 失敗時使用）

舊邏輯保留在 `rule_based_actions`：
1. 三問 SOP（行為斷點有「主動報價」+ 有「尾聲」時觸發）
2. 優先改善最高頻斷點（上條沒觸發時）
3. 當場報價 + ROI（「價格疑慮」≥ 3）
4. 48h 回訪 SOP（「客戶決策延遲」≥ 3 且有 lag_stats）
5. 延伸業務探索（已簽 ≥ 10）

**修改 action 邏輯：** `scripts/build_brief_pdf.py`
- LLM 版：`generate_personalized_actions()` 函式
- Rule-based fallback：`rule_based_actions = []` 那段

## 近一季 vs 更早 趨勢資料（2026-04 新增）

### 用意

強弱項用「近 12 個月平均」判斷，看不出**趨勢**。使用者多次問「這些案型近期是在變好還是變差」。解法：每個 case_type 計算「近一季」vs「更早」兩段資料。

### 計算邏輯（prep_1on1_data.py `_trend_for_type()`）

- **切分**：以 `recent3_months[0]` 為 cutoff（例如 `2026-02-01`），以後為近一季、以前為更早
- **標籤**：
  - `r_signed == 0` → **「近一季無已簽」**（警訊：強項案源流失 / 弱項可能放棄）
  - `e_signed == 0` → **「新成長案型」**
  - `pct(r_unit vs e_unit) >= +10%` → **「變好」**
  - `pct(r_unit vs e_unit) <= -10%` → **「變差」**
  - Else → **「持平」**
- **`small_sample = (r_signed < 3) or (e_signed < 3)`**：小樣本時 label 附加「（樣本小）」，UI 用 ⚠ 灰色顯示避免誤導（n=1 vs n=4 的 -66% 其實只差 1 筆案件）

### prep.json schema

```json
"strengths": [{
  "case_type": "支付命令",
  "my_avg_collected": 38400, ...
  "trend": {
    "recent_n": 1, "recent_signed": 1, "recent_avg_collected": 15000, "recent_sign_rate": 100,
    "earlier_n": 4, "earlier_signed": 4, "earlier_avg_collected": 44250, "earlier_sign_rate": 100,
    "unit_delta_pct": -66.1,
    "trend_label": "變差（樣本小）",
    "small_sample": true
  }
}]
```

### PDF 顯示

強弱項列表每項多一行：
```
⚠ 變差（樣本小） -66%   近一季 1 簽@15,000 ｜ 更早 4 簽@44,250
```

### LLM 使用規則

Prompt 第 4 點明確指引：變差的強項最緊急、變好的弱項延續做對的事、近一季無已簽要警告、small_sample 要謹慎提。

## 同所別 baseline（2026-04 新增）

### 用意

全所 baseline 混入不同組織類型（合署、司法官合署）。司法官合署客單價 $95K、一般所 $62K —— 把所有律師混算 baseline 會扭曲，一般律師可能被司法官合署案件拉高後「顯得客單價低」。

### 所別分布（實測）

| office | 律師數 | 案件數 | 簽約率 | 客單價 |
|---|---|---|---|---|
| 喆律法律事務所 | 65 | 14,836 | 48.8% | $61,553 |
| 喆律法律事務所(合署) | 6 | 2,173 | 46.4% | $53,522 |
| 喆律法律事務所(司法官合署) | 4 | 546 | 35.5% | **$95,696** |

### 計算邏輯（prep_1on1_data.py Step 3b）

- `lid_to_office = {l.id: l.office}` 做 lookup
- `office_cases = [c for c in all_cases if office_match(c.lawyer_id)]`
- `office_type_baseline` 同結構，只用同所別案件
- `overall.office_sign_rate/office_eff/office_avg_unit` **扣掉本人**（避免自己拉高/拉低 baseline）
- `strengths[*]` / `weaknesses[*]` 多 4 欄：`office_baseline_avg_collected`、`office_baseline_n`、`office_unit_gap`、`office_unit_gap_pct`
- 若同所別該 case_type 樣本 < 5 → `office_baseline_avg_collected=None`（顯示「樣本不足」）

### PDF 顯示

**Header metrics** 每個統計欄都有雙 baseline：
```
整體成案率 37.2%
全所 47.3% · 同所別 48.1%
```
附註一行：「同所別」= 喆律法律事務所（不含本人、64 位同事）— 排除合署/司法官合署等結構不同的所別以更公平比較。

**強弱項列表** 每項多一行：
```
全所 21,044 +82.5% ｜ 同所別 22,042 +74.2%（n=493）
```

### LLM 使用規則

Prompt 第 3 點：「優先引用同所別 baseline（更公平），也要提全所以呈現相對位置」。例：「離婚協議書客單價 22,971，同所別基準 30,363（-24%）、全所基準 29,824（-23%）」。

## 律師 per-type 分位 baseline（2026-05 新增）

### 用意

「客單低於基準 -24%」這種抽象 gap % 律師看了沒畫面。改成「全所 17 位律師中你 <P25、P50 是 30K、P75 是 37K」一下子就有對標感。分位的基本單位是**律師個人在該案型的平均客單**（不是案件級客單），代表一個分位點 = 一位律師。

### 計算邏輯（prep_1on1_data.py `_lawyer_unit_dist_by_type` / `_lawyer_unit_dist_by_method`）

- 對每個 case_type，蒐集所有「該案型已簽 ≥ 5 的律師」的個人平均已成案客單價
- 不含本人（避免自己拉高/拉低 baseline）
- **至少 5 位律師合格**才計算分位（< 5 → None，graceful degradation）
- 同所別版用同所律師子集 — 通常小所（如高雄所 6 位）會 < 5 位達門檻、回 None

### prep.json schema

```json
"strengths": [{
  "case_type": "撰寫書狀",
  "firm_unit_p25": 20500, "firm_unit_p50": 23800, "firm_unit_p75": 29500,
  "firm_peer_lawyer_n": 19,
  "firm_peer_position": "≥P75",  // <P25 / P25-P50 / P50-P75 / ≥P75
  "office_unit_p25": null,  // 同所別合格律師 < 5 → None
  ...
}]
```

### LLM 使用規則

Prompt 規則 3 + 6：必須有 ≥ 1 個 action 以分位差為立論主軸；`firm_position == "<P25"` 必明寫「全所 N 位律師中你 <P25、P50 是 X、P75 是 Y」。

## 同年度比較 yearly_compare（2026-05 新增，驗偽年資 confounder）

### 用意

主管常會反問：「客單低是不是因為律師年資久、過往報價就低，平均被拉下來？」這是要先排除的 confounder。`yearly_compare` 直接用「上一個完整年 + 當前年 × 我 vs 全所同年度」回答這個問題。

### 計算邏輯（prep_1on1_data.py Step 5b）

- 用 `max_year = max(case_date)[:4]`，取 `[max_year - 1, max_year]` 兩年
- 對每個 case_type、每個年份：律師個人 (n@avg)、全所扣本人 (n@avg)
- `ratio_pct = my_avg / firm_avg × 100`（100 = 同水準；50 = 律師只有全所一半）

### prep.json schema

```json
"weaknesses": [{
  "case_type": "離婚協議書",
  "yearly_compare": [
    {"year": 2025, "my_signed": 20, "my_avg_collected": 20600, "firm_signed_n": 266, "firm_avg_collected": 31552, "ratio_pct": 65},
    {"year": 2026, "my_signed": 4, "my_avg_collected": 20000, "firm_signed_n": 101, "firm_avg_collected": 34122, "ratio_pct": 59}
  ]
}]
```

### 三種解讀模式（LLM 應掌握）

| 模式 | 觀察 | 結論與 action 方向 |
|---|---|---|
| **每年都低 (< 80%)** | 上年 + 本年都 < 80 | 年資解釋不成立、是個人客單問題；用「分位倒回 P50」當目標 |
| **逐年差距拉開** | ratio_pct 上年 70 → 本年 55（事務所漲價但律師沒跟） | metric 改用「跟上 firm_avg 同年度」而非歷史 P50；this is the most actionable framing |
| **逐年改善** | ratio_pct 上升 | 律師正在追漲、延續做對的事、強化此案型 |

### 反證手法（重要）

若該律師有任一案型同年度 ratio_pct ≥ 150%（例：王郁萱撰寫書狀 165%），就可以 **falsify「能力不夠 / 客單慣性偏低」全面論**。律師敢報高價，只是對特定案型有低報習慣 — 這個觀察用在 action 1 的 why 段非常具說服力。

### LLM 使用規則

Prompt 規則 3 + 8：永遠優先引同年度數字；metric 目標優先用 `yearly_compare[本年].firm_avg`。

## A/B 程序分類與 A 密度分析（2026-05-22 新增）

### 用意

把「成案後的案件」依程序深度二分為 A（完整訴訟程序）vs B（部分程序），算出每位律師的 **A 密度 = 簽成 A 件數 / 總諮詢數**。實證 A 密度與每場諮詢營收強相關 (+0.66)，遠高於成案率 (+0.15) — 律師可以靠多簽 B 案（律師函、協議書、本票裁定）撐高成案率，但每場諮詢營收上不去。brief 必須在 narrative / metrics / action 中**並列「成案率」+「A 密度」**，避免主管被高成案率誤導。

### 程序 tag 完整清單（與 [public/consultation/index.html:4448-4481](public/consultation/index.html#L4448) 同步）

```python
PROC_A_TAGS = {
    '民事一審', '民事二審', '民事三審',
    '家事一審', '家事二審', '家事三審',
    '刑事偵查程序', '刑事一審程序', '刑事二審程序', '刑事三審程序',
    '刑事告訴', '刑事再議程序',
    '刑事附帶民事一審程序', '刑事一審附帶民事',
    '強制執行', '強制執行(五年)',
    '抗告', '暫時保護令抗告',
    '通常保護令程序', '暫時處分',
    '家事調解程序', '勞動爭議調解',
    '改定監護', '收養程序', '確認親子關係',
    '假扣押聲請', '聲請核發債權憑證', '聲請限定繼承程序',
    '履行同居', '法院分別財產制登記',
    '包套',
}
PROC_B_TAGS = {
    '律師函', '存證信函',
    '離婚協議書', '婚姻中協議', '和解協議書', '還款協議書',
    '撰寫和解書', '協議書撰寫',
    '代協商', '律師協商', '陪同調解', '調解聲請狀',
    '撰寫書狀', '民事起訴狀撰寫',
    '證人', '警詢', '陪偵', '閱卷', '律見',
    '公證費', '代筆遺囑',
    '支付命令', '本票裁定',
    '法律顧問', '常年企業法律顧問', '契約',
    '請求履行協議',
}

A_SUB = {
    '民事': {'民事一審', '民事二審', '民事三審'},
    '家事': {'家事一審', '家事二審', '家事三審',
            '改定監護', '收養程序', '確認親子關係',
            '履行同居', '法院分別財產制登記'},
    '刑事': {'刑事偵查程序', '刑事一審程序', '刑事二審程序', '刑事三審程序',
            '刑事告訴', '刑事再議程序',
            '刑事附帶民事一審程序', '刑事一審附帶民事'},
    '執行救濟': {'強制執行', '強制執行(五年)', '抗告', '暫時保護令抗告',
              '通常保護令程序', '暫時處分',
              '假扣押聲請', '聲請核發債權憑證', '聲請限定繼承程序'},
    '調解': {'家事調解程序', '勞動爭議調解'},
    '包套': {'包套'},
}
```

### A 密度計算邏輯

```python
def has_a(case_tags):
    return any(t in PROC_A_TAGS for t in case_tags)

# Per lawyer
a_count = sum(1 for c in cases if c.is_signed and has_a(tags(c.case_type)))
total_consult = len(cases)
a_density = a_count / total_consult * 100  # 全所平均 22.8%
```

### 全所基線（2026-05 實測，n=29 在職律師、諮詢數 ≥ 50）

| 指標 | 全所平均 |
|---|---|
| A 密度 | **22.8%** |
| 成案率 | 48.4% |
| A 案平均單價 | 10 萬 |
| B 案平均單價 | 2.5 萬（A/B = 3.9x） |
| 每場諮詢營收 | 3.2 萬 |

### A 次類別分布（2026-05 實測）

| 次類別 | 件數佔 A% | 中位單價 | 全所案件 n |
|---|---|---|---|
| 家事 | 44% | 9.2 萬 | 1,541 |
| 刑事 | 21% | 8.2 萬 | 698 |
| 民事 | 18% | 9.2 萬 | 634 |
| 執行救濟 | 11% | **5.1 萬**（最低） | 378 |
| 包套 | 5% | **12.0 萬**（最高） | 146 |
| 調解 | 1% | 8.0 萬 | 19 |

### prep.json schema 建議

```json
"a_density": {
  "my_a_count": 308,
  "my_total_consult": 1229,
  "my_a_density_pct": 25.1,
  "firm_a_density_pct": 22.8,
  "gap_pct": +2.3,
  "a_by_sub": {
    "家事": {"n": 184, "pct_of_my_a": 60, "avg_unit": 97000, "firm_median": 92000},
    "民事": {"n": 56, "pct_of_my_a": 18, "avg_unit": 92000, "firm_median": 92000},
    "刑事": {"n": 27, "pct_of_my_a": 9, "avg_unit": 100000, "firm_median": 82000},
    "執行救濟": {"n": 31, "pct_of_my_a": 10, "avg_unit": 46000, "firm_median": 51000},
    "包套": {"n": 9, "pct_of_my_a": 3, "avg_unit": 97000, "firm_median": 120000},
    "調解": {"n": 1, "pct_of_my_a": 0, "avg_unit": 80000, "firm_median": 80000}
  }
}
```

### LLM 使用規則

1. **narrative 必提**：A 密度 +/- vs 全所基線 22.8%，是 brief 第一段必出現的數字之一
2. **不可只報成案率**：若律師成案率高但 A 密度低（廖懿涵模式），narrative 必須點明這個 pattern
3. **無包套產品的律師**：若 `a_by_sub.包套.n == 0` 且諮詢量 ≥ 300，action 中要列「推廣包套產品」項
4. **執行救濟比例高的律師**：若 `a_by_sub.執行救濟.pct_of_my_a ≥ 15%`，action 中要點出「執行救濟單價偏低，是否案件結構需調整」
5. **A 密度顯著低的律師**（< 15%）：action 必含「諮詢轉 A 案能力提升」項，metric 目標寫「下季 A 密度從 X% 提升到 Y%」

### 案件級單價分位（per-lawyer per-A-subtype）

對律師個人在單一 A 次類別內的所有已成案案件，計算 P25/P50/P75/P90/max。用「分位 vs 全所同類分位」做對照，比平均單價更具說服力。

```python
import statistics
prices = sorted([c.revenue for c in lawyer_cases if c.is_signed and a_subtype_of(c) == '家事' and c.revenue > 0])
p25, p50, p75 = statistics.quantiles(prices, n=4)
```

**警示訊號**：若律師個人 P75 ≤ 全所同案型 P50，代表此律師最好的 25% 案件才達到全所中位 — 是「整體定價偏低」的鐵證。範例：廖懿涵家事一審 P75=9.2 萬，全所家事案件級 P50=9.2 萬 → 警示。腳本：[scripts/analyze_density_pricing.py](scripts/analyze_density_pricing.py)。

## 討論問題產生的雜訊閾值（避免小樣本/小差異提問）

所有依資料產生的討論問題都要通過閾值才問，避免問雜訊：

| 問題類型 | 門檻 | 理由 |
|---|---|---|
| 主力案型成案率下滑 | `r_n ≥ 10` 且 `rate_delta ≤ -10%` | 5 筆樣本 100%→80% 只差 1 筆，是雜訊 |
| 效益值下滑 | 絕對 ≥ 10,000 **且** 相對 ≥ 15% **且** `r_n ≥ 5` | 5K/120K = 4% 在小樣本是雜訊 |
| 弱項（客單價）| `my_signed ≥ 10` 且 `abs(unit_gap_pct) ≥ 15%` | n=6 客單低是特性；gap < 15% 是雜訊 |

弱項提問只選「已成案客單價顯著低於全所基準」（不再用成案率 — 提案 B 後成案率欄已移除）。

## Narrative lead 的 2×2 組合邏輯

Header 的 narrative 敘事**必須依「成案率變動」×「效益變動」的 2×2 組合**挑對應文案，不可以寫死某一種 pattern。閾值：成案率 ±1%、效益 ±1,000/人（以內視為持平）。

| 成案率變動 | 效益變動 | 敘事結論 |
|---|---|---|
| 升 | 降 | 接得到更多案子，但每件收得較少（客單價下滑是主要問題）— 洪琬琪模式 |
| 降 | 升 | 選擇接高價案件，成案率下滑但客單價提升（若刻意策略選擇可接受）|
| 降 | 降 | **成案率與客單價同時下滑**——不是單純策略取捨，兩個指標都在弱化 — 林桑羽模式 |
| 升 | 升 | 成案率與客單價同步提升（整體變好）|
| 持平 | 持平 | 整體變動不大，屬於月度波動範圍 |

**常見誤用**：若只看效益變動寫死「接更多但每件少」的 narrative（原版 bug），會在林桑羽這種兩者都下滑的案件上輸出錯誤敘事。務必同時檢查兩個變動方向。

### 2×2 還不夠 — 必須加 A 密度當「成案率訊號的去毒劑」（2026-05-22 補強）

2×2 只能判斷「成案率」+「效益」**期間變動**，但無法捕捉一種重要情境：**「升 升 / 持平」case 中律師其實仍在低效運作**（成案率高但都是 B 案、效益剛好過得去）。廖懿涵就是這個 trap — 成案率全所第二（56.4%）、效益看似穩定（2.42 萬），但 A 密度只 19.4% 遠低於全所 22.8%，**期間變動指標完全抓不到**。

**補強規則**：narrative 寫完 2×2 結論後，必須再檢查 A 密度水位：

| A 密度 vs 全所 22.8% | 加上的 narrative 段 |
|---|---|
| 高於 +3% 以上 | 「諮詢轉完整訴訟程序的密度高於全所平均，產出結構偏向高毛利案件」 |
| 介於 ±3% 內 | 不額外提（持平） |
| 低於 −3% 以上 | 「諮詢轉完整訴訟程序的密度低於全所平均，雖然成案率不差，但案件結構偏向部分程序（律師函/協議書等低單價案件）」 |
| 低於 −7% 以上 | **必須升級**為 narrative 主軸：「成案率/效益看似 X，但 A 密度顯著偏低 (Y% vs 全所 22.8%)，是當前最關鍵的結構性問題」 |

## 案例引用必做 QA（手寫工作表、narrative、1-on-1 議程時）

**教訓**：曾有把「林芝芑（陪偵已簽）」跟「陳楚寒（妨害兵役未簽）」張冠李戴的錯誤（兩人都是 1-2 月、刑事相關、案情複雜）— 主管當場念給律師聽，立刻被抓到錯誤。

**預防規則**：**任何手寫引用案例時，必須從 `prep.json` 或 DB 查證以下欄位**：

```python
import json
prep = json.load(open('briefs/raw_data/{律師名}_prep.json', encoding='utf-8'))
lookup = {c['id']: c for c in prep['cases_with_meeting_record']}
# 查某個當事人的實際資料
for c in prep['cases_with_meeting_record']:
    if c.get('client_name') == '要確認的當事人名':
        print(c['case_date'], c['case_type'], c['is_signed'], c['collected'])
        print((c.get('meeting_record') or '')[:200])  # 看 meeting_record 前 200 字
```

**每則案例引用必寫這 5 欄**：當事人 · 日期 · case_type · is_signed · 收款金額。範本：
> **陳楚寒**（2026-02-06 · 現場諮詢 · **未簽** 2,000）

**不可以**憑記憶寫「刑事案、一月、未簽」這種模糊描述 — 近似特徵案件容易混淆。

**驗證工具**（生成 PDF / 工作表後都跑一次）：

```python
# 檢查 analysis JSON 裡有沒有誤提其他當事人
all_clients = {c['client_name'] for c in prep['cases_with_meeting_record'] if c.get('client_name')}
for f in Path('briefs/raw_data/{律師名}_batches').glob('analysis_*.json'):
    d = json.loads(f.read_text(encoding='utf-8'))
    real = lookup.get(d['case_id'], {}).get('client_name')
    content = json.dumps(d['analysis'], ensure_ascii=False)
    for name in all_clients:
        if name and name != real and name in content:
            print(f'{f.name}: 實際 {real} 但內文提到 {name}')
```

## 追蹤機制必須動態生成

**絕對不能**硬寫某個律師的「三問」/ 特定百分比 / 特定斷點名稱。`build_brief_pdf.py` 中追蹤機制三層：

1. **每週自檢**：引用 `actions[0]['title']` 的動作
2. **期中回顧**：追蹤 `behavior_counts[0]` 的斷點名稱和次數
3. **下次 1-on-1 指標**：
   - 整體諮詢效益：目標 = `recent_agg.consult_eff × 1.15`（近 3 月基準 + 15%）
   - 已簽客單價：目標 = `recent.collected/signed_count × 1.15`
   - 失敗原因 top 2 合計占比：目標 = 目前 × 0.65
   - 最高頻行為斷點：目標 = 目前 × 0.5

**如果看到追蹤機制寫「三問」、22,935、65,000、30 次這些特定數字**，代表誤用洪琬琪的版本，必須回來修動態邏輯。

## 常見問題

### 會議記錄 zip 上傳後 DB 還是看不到

檔名格式必須對：`律師名_成案/未成案_YYYYMMDD_案件類型(會議記錄|逐字稿).docx`。比對規則在 `public/index.html` 約 line 3286。

### LLM 分析遇到 429 rate limit

腳本內建：
- 滾動 60 秒窗口追蹤 tokens 使用，自動 throttle
- SDK `max_retries=10`
- 單筆 > 9k tokens 時放行讓 SDK 的 Retry-After 處理

若連續 429 超過 3 次失敗才 skip。skip 掉的案件下次 `--force` 重跑。

### `build_brief_pdf.py` 呼叫 LLM 時遇到 429

`build_brief_pdf.py` 的 `generate_personalized_actions()` 也會吃 10K tokens/min 的 rate limit。一份 brief 的 prompt 約 20-23K tokens — 一個窗口只能跑半份。連跑兩位律師必觸發 429。

**解法**：`max_retries=10` + `timeout=180` 讓 SDK 自己退避重試，大約等 60-120s 後自動繼續。**不要把 max_retries 降回 2**（試過，會直接炸）。

### LLM 回傳 JSON 被截斷（JSONDecodeError: Unterminated string）

LLM 產 personalized actions 時，輸出 token 若超過 `max_tokens` 就會被截斷，JSON 不完整。

**解法**：
1. `max_tokens=6000`（**不能降到 4000**，林桑羽曾輸出 5257 tokens 觸發）
2. `_try_recover_actions_json()` 會切到最後一個完整的 action 的 `}` 後補 `]}` 自救

實測洪琬琪的輸出常 3000 tokens、林桑羽偶爾 > 5000、劉奕靖通常 3200-3600。

### `llm_analyze_cases.py` 卡死不動

劉奕靖實測：跑到第 8 筆整個腳本 hang 2+ 小時（Python process 存活、output 檔 mtime 不更新）。根因不明（可能 SDK retry 進入死迴圈）。

**偵測**：`ls -la <output_file>` 看 mtime，超過 3-5 分鐘沒更新就判 hang。

**解法**：kill 掉，用 `llm_analyze_resume.py`。它短 timeout（90s）、少 retry（2）、per-case try/except — 卡單筆直接跳下一筆。

```bash
# kill stuck python
taskkill //F //PID <pid>
# 換 resume 版
python llm_analyze_resume.py "律師姓名"
```

### Rate limit 導致連跑 2 位律師 PDF 失敗

實測洪琬琪跑完立刻跑林桑羽會觸發 429。兩個選項：
1. **序列跑、讓 SDK 退避**（預設、簡單）— `max_retries=10` 會在 60-120s 後自動重試
2. **保留 HTML 重產 PDF**（進階）— 用 playwright 直接把已存的 `{name}_brief.html` 轉 PDF，不重呼 LLM

```python
from playwright.sync_api import sync_playwright
from pathlib import Path
OUT = Path(r'briefs')
names = ['劉奕靖', '林桑羽', '洪琬琪']
with sync_playwright() as p:
    browser = p.chromium.launch()
    for name in names:
        html_path = OUT / f'{name}_brief.html'
        pdf_path = OUT / f'{name}_brief.pdf'
        page = browser.new_page()
        page.goto(f'file:///{html_path.resolve().as_posix()}')
        page.emulate_media(media='print')
        page.pdf(path=str(pdf_path), format='A4',
                 margin={'top':'12mm','right':'14mm','bottom':'12mm','left':'14mm'},
                 print_background=True)
        page.close()
    browser.close()
```

### tee 或 pipe 輸出造成 `ValueError: I/O operation on closed file`

`llm_analyze_resume.py` 跑在 `| tee` 或 `| tail` 後面時，Python 的 `sys.stdout` wrapper 配合 pipe 關閉會炸。

**解法**：不用 tee/pipe，改 `python xxx.py > log.txt 2>&1` 檔案重導向。或設 `PYTHONIOENCODING=utf-8` 跳過 wrapper（`llm_analyze_resume.py` 已這樣做）。

### case_type「(未指定案件內容)」被當強項？

**原因**：全所基準的未指定案件內容成案率也低（因為這等於未成案的近似指標），所以律師的未指定 vs 基準 gap 可能是正值（誤認為強項）。

**解法**：`prep_1on1_data.py` 已在 Step 5 的 gaps 計算排除「(未指定案件內容)」，不進強弱項比較。另外 `build_brief_pdf.py` 的 `strengths_types` 也過濾掉。

### 為什麼各案型成案率都 > 50% 但整體只 30%？

**統計偏誤**：律師的 case_type 欄位登錄習慣 — 只對已成案案件補填具體案件內容，未成案的只留「現場諮詢 / 視訊諮詢」。所以：
- 已簽約 → `case_type = "現場諮詢, 支付命令"` → 進支付命令類別分子分母
- 未簽約 → `case_type = "現場諮詢"` → 進「(未指定案件內容)」，不會進支付命令的分母

結果：支付命令類別成案率被系統性高估（分母少掉了絕大部分的非成案諮詢）。

PDF 的「近 3 月成案率拆解」+ 偏誤警告框就是為了讓律師看到這個偏誤。**實務建議**：律師應把未成案諮詢也補填案件內容欄位（例如「支付命令（未成案）」），才能反映真實拒絕比例。

### 右截尾偏誤（近期案件之後才會簽）

腳本自動算簽約滯後分布並判斷：
- `within_30 >= 80%`：右截尾偏誤小，近期數字可信
- `60% ~ 80%`：可能低估 5-10%
- `< 60%`：建議用 60 天前案件比較

洪琬琪 89% 在 30 天內簽 → 偏誤可忽略。劉奕靖/林桑羽要個別看。

## 關鍵決策：客單價優先 vs 成案率優先

**使用者明確表達過**：成案率下滑若是「提高收費導致」，且效益值維持/上升，這是**可接受的策略選擇**，不要當問題處理。

實務上這影響 action 產生的邏輯：
- 不要生成「回升 XX 成案率」的 action
- 優先生成「拉客單價」或「救回已流失但還有機會的客戶」的 action
- 追蹤指標以**整體諮詢效益**為首要，成案率次要

## 關鍵決策：案件內容的成案率/效益值**禁止使用**（提案 B）

**強制規則**：因為登錄偏誤（律師只對已成案補填具體案件內容），以下**絕對不能**出現在 PDF：
- 「案件內容 × 成案率」比較（無論是強弱項、趨勢變動、或敘事）
- 「案件內容 × 效益值（收款/諮詢數）」比較

**可以用**：
- 整體成案率（分母是律師的全部案件 → 可靠）
- 諮詢型態（現場/視訊/電話）× 成案率（每次諮詢都會填 → 可靠）
- 案件內容 × **已成案客單價** vs 全所同類別基準（分子分母都是已成案 → 可靠）
- AI 歸因失敗原因（跟 case_type 無關 → 可靠）
- 行為斷點（跟 case_type 無關 → 可靠）

## 偵測登錄偏誤（跑其他律師時先檢查）

跑新律師前執行這段，確認登錄偏誤是否存在（若已不存在，才可以回歸舊版「案件內容 × 成案率」分析）：

```python
cd /c/projects/lawyer-dashboard/scripts && python -c "
import os, io, sys, httpx, re
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv('.env', override=True)
URL=os.environ['SUPABASE_URL']; KEY=os.environ['SUPABASE_SERVICE_KEY']
HDR={'apikey':KEY,'Authorization':f'Bearer {KEY}'}
name = '律師姓名'
r=httpx.get(f'{URL}/rest/v1/lawyers', params={'select':'id','name':f'eq.{name}'}, headers=HDR)
lid = r.json()[0]['id']
rows, off = [], 0
while True:
    r=httpx.get(f'{URL}/rest/v1/consultation_cases',
        params={'select':'case_type,is_signed','lawyer_id':f'eq.{lid}','limit':'1000','offset':str(off)}, headers=HDR)
    b=r.json(); rows.extend(b)
    if len(b)<1000: break
    off+=1000
CONSULT={'現場諮詢','視訊諮詢','電話諮詢'}
signed_no_content = signed_with_content = unsigned_no_content = unsigned_with_content = 0
for c in rows:
    t=c.get('case_type') or ''
    parts=[p.strip() for p in re.split(r'[,，、]', t) if p.strip()]
    has_content = any(p not in CONSULT for p in parts)
    if c.get('is_signed'):
        if has_content: signed_with_content+=1
        else: signed_no_content+=1
    else:
        if has_content: unsigned_with_content+=1
        else: unsigned_no_content+=1
print(f'{name}:')
print(f'  已簽：{signed_with_content+signed_no_content}（有案件內容 {signed_with_content}, 無 {signed_no_content}）')
print(f'  未簽：{unsigned_with_content+unsigned_no_content}（有案件內容 {unsigned_with_content}, 無 {unsigned_no_content}）')
if (signed_with_content + unsigned_with_content) > 0:
    signed_pct = signed_with_content / (signed_with_content + unsigned_with_content) * 100
    print(f'  在「有填案件內容」的案件中，已簽占 {signed_pct:.0f}% — 若 > 70% 即為顯著登錄偏誤')
"
```

**判讀規則**：
- 「有填案件內容」中已簽占比 > 70% → 顯著偏誤，**必須走提案 B**
- 50-70% → 中度偏誤，仍建議走提案 B
- < 50% → 偏誤小，可考慮用舊版（但暫未實作該分支）

## 成本估算

| 案件數 | API 成本 | 時長（含 throttle）|
|---|---|---|
| 10 筆 | ~$0.4 | 5-10 分鐘 |
| 30 筆 | ~$1.2 | 15-30 分鐘 |
| 50 筆 | ~$2 | 30-60 分鐘 |
| 100 筆 | ~$4 | 60-90 分鐘 |
| 150 筆 | ~$6 | 90-120 分鐘 |

## 檔案位置

- 腳本：`C:/projects/lawyer-dashboard/scripts/`
  - `prep_1on1_data.py` — 唯讀抽資料（產 `_prep.json`）
  - `llm_analyze_cases.py` — LLM 歸因主腳本（Claude Sonnet 4.5）**實測會偶爾 hang，見 FAQ**
  - `llm_analyze_resume.py` — LLM 歸因的 resume 版（短 timeout、少 retry、卡單筆跳下一筆）
  - `build_brief_pdf.py` — PDF 生成（內含 `generate_personalized_actions()` LLM action 產生器）
- 資料：`C:/projects/lawyer-dashboard/scripts/briefs/raw_data/`
  - `{律師名}_prep.json` — Step 1 產出
  - `{律師名}_llm.json` — Step 2 產出（與 DB `consultation_cases.llm_analysis` 同步）
- 產出：`C:/projects/lawyer-dashboard/scripts/briefs/{律師名}_brief.pdf` + `{律師名}_brief.html`
- 環境變數：`C:/projects/lawyer-dashboard/scripts/.env`
  - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`（service role）
  - `ANTHROPIC_API_KEY`（load_dotenv 要用 `override=True`，否則讀不到系統已有的 env）

## DB Schema 依賴

- `lawyers`：`id, name, office, is_active, role`
- `consultation_cases`：`id, lawyer_id, case_date, case_type, case_number, client_name, is_signed, revenue, collected, meeting_record, transcript, lawyer_notes, llm_analysis, llm_analyzed_at`
- `revenue_records`：`record_date, client_name, assigned_lawyers, amount`（用來算簽約滯後）
- Migration `20260417000000_add_llm_analysis.sql` 必須先跑過
