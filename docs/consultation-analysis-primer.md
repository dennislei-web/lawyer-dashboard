# 諮詢效益分析 Primer（給許秉權）

> 這份文件給「不寫程式、用 Supabase Dashboard SQL Editor + Claude.ai」的分析夥伴。
> 目的：跟 Claude 討論「怎麼提升喆律的諮詢效益」時不用每次從頭解釋背景。

---

## ⚠️ 安全紅線（請先讀這段）

你在 Supabase 的角色是 **Developer**（這是我們方案下能給的最小權限，Read-only 要 Supabase Team plan 才有）。Developer 在 SQL Editor 技術上**可以執行 INSERT / UPDATE / DELETE / DROP**，但**禁止**這樣做。

**你只能跑 `SELECT` query。** 不確定一段 SQL 是不是 SELECT、或 Claude 給你的 SQL 看起來在改資料，**先停下來問 Dennis**。

特別禁止的指令：
- `INSERT` / `UPDATE` / `DELETE`（會改變業務資料）
- `DROP` / `TRUNCATE` / `ALTER`（會破壞 schema）
- `CREATE`（除非是 `CREATE TEMP TABLE` 暫存查詢結果，否則一律先問）

> 違反一次可能造成不可逆損失，全所數據都在這裡面。

---

## 0. 你的工作流（每次討論）

1. 打開 [Supabase Dashboard](https://supabase.com/dashboard) 進 `lawyer-dashboard` 專案 → 左側 `SQL Editor`
2. 想到一個假設 → 跑 query → 把結果（CSV 或 markdown table）複製
3. 打開 [Claude.ai](https://claude.ai)（建議用桌面版 Claude Desktop） → 開新對話 → **第一步先貼下面「§1 開場訊息」**
4. 把你的問題 + SQL 結果貼進去，跟 Claude 討論
5. Claude 可能會回饋「再跑這個 query 看看」→ 你回 Supabase 跑 → 結果貼回來

---

## 1. 開場訊息（每次新對話的第一句，直接複製貼上）

```
你是喆律法律事務所的諮詢效益顧問。我會貼從 Supabase 跑出來的 SQL 結果給你討論。

【角色】我（許秉權）負責分析喆律的諮詢成效並提出改善建議。我不寫程式，數據從 Supabase Dashboard SQL Editor 拉。

【核心分析框架，請內化】
1. 「每場諮詢營收」是首要指標，成案率次要 — 客單上升伴隨成案率下滑可能是「選擇接高價案」的策略結果，不是問題。
2. **登錄偏誤警告**：律師只對已簽案件補填具體 case_type，未成案 94.8% 是「(未指定案件內容)」。所以「案件內容 × 成案率」「案件內容 × 客單價」這兩個切法**不能用**（分母被抽掉會誤導）。可用的：整體成案率、諮詢型態（現場/視訊）成案率、已成案客單價。
3. **A/B 程序分類** — A = 完整訴訟程序（民/家/刑各審、強執、保護令、家事/勞動調解、改定監護等），B = 部分程序（律師函、撰寫書狀、支付命令、本票裁定等）。**A 密度 = A 案件數 / 總諮詢數**（不是 / 已成案），全所平均 22.8%。A 密度 vs 每場諮詢營收相關係數 +0.66，比成案率（+0.15）強得多 — 不要只看成案率管律師。
4. **A 內部六大類**：包套（單價 13 萬，高毛利核武）、家事/民事/刑事各審（~10 萬）、調解（8 萬）、執行救濟（僅 6 萬，低毛利）。包套極度集中於雷皓明；「執行救濟比例偏高」的律師要點出低毛利。
5. **客單價要看「律師間分位」+「案件級分位」** — 律師個人 P50 vs 全所律師 P25/P50/P75 比較（律師間分位），加上律師在該案型個別案件的 P25/P75 分散度（看敢不敢開高價）。
6. **同年度比較破解年資 confounder** — 律師客單低時主管常反問「是不是他年資久報價就低」。用 ratio_pct = 律師同年 / 全所同年；若**逐年下降**代表「事務所漲了但這位律師沒跟上」（比靜態低更具行動性）；若某案型 ratio_pct ≥ 150% 可反證「能力不夠」說法不成立。
7. **視訊/電話諮詢「沒當場簽契約」不算失敗** — 線上諮詢律師本來就是會後傳契約。
8. **歸因「客戶不敢加 LINE」之前，必須查 consultation_cases.line_chat_url** — 有值代表後續確實建立 LINE 對話，不能歸因為「通道死掉」。

【資料表（Supabase）】
- `lawyers`：id, name, office, role
- `consultation_cases`：id, lawyer_id, case_date, case_type, case_number, client_name, is_signed, revenue, collected, meeting_record, transcript, lawyer_notes, llm_analysis, line_chat_url
  - case_type 同時含「諮詢型態」（現場諮詢/視訊諮詢/電話諮詢）+「案件內容」（民事一審/家事一審/支付命令/包套...），逗號分隔
- `revenue_records`：record_date, client_name, assigned_lawyers, amount（用來算簽約滯後 = revenue.record_date − consultation_cases.case_date）

【回答風格】
- 全中文，避免 SOP/ROI/cross-sell/momentum 等英文術語
- 引用案件一律帶「當事人姓名 + 案號」
- 不要把 percentage point 寫成 pp，一律用 %
- 給的 action 必須有「下個月怎麼看進展」的明確數字驗收標準
```

---

## 2. Supabase Dashboard SQL Editor 用法

- 進專案後左側選 `SQL Editor`
- 點 `+ New query`，貼 SQL 進去 → `Run`（Cmd+Enter）
- 結果在下方表格，可以點右上 `Download` → CSV，或用 `Copy as Markdown` 直接複製給 Claude

---

## 3. 起手 SQL 範本（5 個必跑）

> 直接複製貼到 SQL Editor 就能跑。覺得 Claude 給你的 SQL 看不懂時，回到這份範本對照。

### 3.1 全所 A 密度排行（前 15 名）

```sql
WITH a_codes AS (
  SELECT unnest(ARRAY[
    '民事一審','民事二審','民事三審','家事一審','家事二審','家事三審',
    '刑事一審','刑事二審','刑事三審','強制執行','保護令','家事調解',
    '勞動調解','改定監護','收養','確認親子','假扣押','聲請限定繼承','包套'
  ]) AS code
)
SELECT
  l.name AS 律師,
  l.office AS 接案所,
  COUNT(*) AS 總諮詢,
  SUM(CASE WHEN cc.is_signed THEN 1 ELSE 0 END) AS 已成案,
  SUM(CASE WHEN cc.is_signed AND EXISTS (
    SELECT 1 FROM a_codes WHERE cc.case_type LIKE '%'||a_codes.code||'%'
  ) THEN 1 ELSE 0 END) AS A案數,
  ROUND(100.0 * SUM(CASE WHEN cc.is_signed AND EXISTS (
    SELECT 1 FROM a_codes WHERE cc.case_type LIKE '%'||a_codes.code||'%'
  ) THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS A密度_pct
FROM consultation_cases cc
JOIN lawyers l ON l.id = cc.lawyer_id
WHERE cc.case_date >= '2025-01-01'
GROUP BY l.name, l.office
HAVING COUNT(*) >= 20
ORDER BY A密度_pct DESC
LIMIT 15;
```

### 3.2 律師每場諮詢營收 vs 全所平均（揭露能力 vs 案件量的不對稱）

```sql
SELECT
  l.name AS 律師,
  COUNT(*) AS 總諮詢,
  ROUND(SUM(COALESCE(cc.collected, 0)) / NULLIF(COUNT(*), 0) / 10000.0, 2) AS 每場諮詢營收_萬,
  ROUND(100.0 * SUM(CASE WHEN cc.is_signed THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS 成案率_pct
FROM consultation_cases cc
JOIN lawyers l ON l.id = cc.lawyer_id
WHERE cc.case_date >= '2025-01-01'
GROUP BY l.name
HAVING COUNT(*) >= 20
ORDER BY 每場諮詢營收_萬 DESC;
```

### 3.3 客單價同年度比較（破解年資 confounder）

```sql
WITH yearly AS (
  SELECT
    l.name,
    EXTRACT(YEAR FROM cc.case_date)::int AS yr,
    AVG(cc.collected) FILTER (WHERE cc.is_signed AND cc.collected > 0) AS my_avg,
    COUNT(*) FILTER (WHERE cc.is_signed) AS my_n
  FROM consultation_cases cc
  JOIN lawyers l ON l.id = cc.lawyer_id
  WHERE cc.case_date >= '2024-01-01'
  GROUP BY l.name, EXTRACT(YEAR FROM cc.case_date)
),
firm AS (
  SELECT
    EXTRACT(YEAR FROM case_date)::int AS yr,
    AVG(collected) FILTER (WHERE is_signed AND collected > 0) AS firm_avg
  FROM consultation_cases
  WHERE case_date >= '2024-01-01'
  GROUP BY EXTRACT(YEAR FROM case_date)
)
SELECT
  y.name AS 律師, y.yr AS 年度,
  y.my_n AS 我簽案數,
  ROUND(y.my_avg/10000.0, 1) AS 我客單_萬,
  ROUND(f.firm_avg/10000.0, 1) AS 全所客單_萬,
  ROUND(100.0 * y.my_avg / NULLIF(f.firm_avg, 0), 1) AS ratio_pct
FROM yearly y
JOIN firm f ON f.yr = y.yr
WHERE y.my_n >= 5
ORDER BY y.name, y.yr;
```

→ 看完問 Claude：「哪些律師的 ratio_pct **逐年下降**？這些人是『漲價沒跟上』的優先 1-on-1 對象」

### 3.4 簽約滯後分布（找出 follow-up 通道是否健康）

```sql
SELECT
  l.name AS 律師,
  COUNT(*) AS 簽案數,
  ROUND(AVG(EXTRACT(EPOCH FROM (rr.record_date - cc.case_date)) / 86400)::numeric, 1) AS 平均滯後天,
  ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (rr.record_date - cc.case_date)) / 86400))::numeric, 1) AS 中位滯後天
FROM consultation_cases cc
JOIN lawyers l ON l.id = cc.lawyer_id
JOIN revenue_records rr ON rr.client_name = cc.client_name
WHERE cc.is_signed = true
  AND cc.case_date >= '2025-01-01'
  AND rr.record_date >= cc.case_date
GROUP BY l.name
HAVING COUNT(*) >= 5
ORDER BY 中位滯後天 DESC;
```

→ 中位滯後超過 30 天的律師，問 Claude：「他的 follow-up 模式有什麼可優化？」

### 3.5 已簽案件的月趨勢 × 來源管道（找出哪個 channel 在掉）

> 註：`consultation_cases` 沒有 source channel 欄位 — channel 資料在 `revenue_records.source_channel`（也就是「簽下來的案子」的來源）。所以這個 query 看的是 **已簽案件**的 channel 變化，不是諮詢進案的 channel。

```sql
SELECT
  TO_CHAR(rr.record_date, 'YYYY-MM') AS 月份,
  COALESCE(NULLIF(rr.source_channel, ''), '(未填)') AS 來源管道,
  COUNT(*) AS 簽案數,
  ROUND(SUM(rr.collected) / 10000.0, 1) AS 實收_萬,
  ROUND(AVG(rr.collected) / 10000.0, 2) AS 平均客單_萬
FROM revenue_records rr
WHERE rr.record_date >= '2024-06-01'
  AND rr.is_void = false
  AND rr.brand IN ('zhelu', '85010', 'moneyback')
GROUP BY TO_CHAR(rr.record_date, 'YYYY-MM'), rr.source_channel
ORDER BY 月份 DESC, 簽案數 DESC;
```

→ 想看「諮詢量本身」的月趨勢（不分 channel），跑這個：

```sql
SELECT TO_CHAR(case_date, 'YYYY-MM') AS 月份,
       COUNT(*) AS 諮詢數,
       SUM(CASE WHEN is_signed THEN 1 ELSE 0 END) AS 已簽,
       ROUND(100.0 * SUM(CASE WHEN is_signed THEN 1 ELSE 0 END) / COUNT(*), 1) AS 成案率_pct
FROM consultation_cases
WHERE case_date >= '2024-06-01'
GROUP BY TO_CHAR(case_date, 'YYYY-MM')
ORDER BY 月份 DESC;
```

---

## 4. 已知 Pitfall

1. **登錄偏誤**：避免用「案件內容 × 成案率」「案件內容 × 客單價」（理由見 §1 開場第 2 條）
2. **同名律師**：合署律師 office 可能跟喆律本身的律師重疊，跑全所比較時要 filter `office = '喆律法律事務所'`
3. **資料時間範圍**：consultation_cases 從 2024 年下半開始才填得完整，2024 上半的資料量稀少
4. **discontinued users**：lawyers.is_active = false 的人歷史諮詢還在，做活躍律師排行要加 filter `l.is_active = true`
5. **collected vs revenue**：`revenue` 是契約金額、`collected` 是實際收到金額，效益分析優先用 `collected`

---

## 5. 卡關問誰

- **數據對不上、SQL 跑不動** → 問 Claude（貼錯誤訊息）
- **看到很怪的數字** → 截圖儀表板對應頁、貼 SQL 結果，問 Dennis
- **想改儀表板某個顯示** → 寫 spec 給 Dennis，他和 Claude Code 處理

---

最後一句忠告：**先建立假設、再跑 SQL 驗證**。不要先跑 100 個 query 再想故事 — Claude 跟你討論時會幫你形成假設。
