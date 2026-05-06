-- ============================================
-- 合署律師分潤歸屬 (partner attribution)
--
-- 為每筆 revenue_records 計算「喆律端應入帳金額」(firm_amount)。
-- 規則參數放在 lawyers.partner_terms (jsonb)，由 ETL 套用。
--
-- 識別流程（per record）：
--   fl = assigned_lawyers 第一位律師
--   if fl 不是 partner（partner_terms is null）→ firm_amount = amount × 1.0  (firm_default)
--   if fl 是 partner:
--     if group_name 是 fl 自合署組（含 fl 的名字）:
--       if amount == consult_fee_amount AND NOT self_take_includes_consult_fee:
--         → consult_fee
--       else:
--         → self_take
--     elif amount == consult_fee_amount:
--       → consult_fee
--     else:
--       → case_close
--
-- partner_terms 結構：
--   {
--     "self_take_firm_pct": 0.30,                  -- 自帶承辦時喆律拿
--     "consult_fee_amount": 2000,                  -- 視為諮詢費的單筆金額
--     "consult_fee_firm_pct": 0.00,                -- 諮詢費喆律拿（雪莉=0；顯皓=1）
--     "case_close_firm_pct": 0.95,                 -- 諮詢成案後一般委任費喆律拿
--     "self_take_includes_consult_fee": true,      -- 自合署組裡 2000 是否也按 self_take 算
--                                                   -- 雪莉/昭萱/煜婕 = true; 顯皓 = false
--     "monthly_firm_cost": 0,                      -- 喆律每月固定支出（顯皓 = 130000）
--     "notes": "..."
--   }
-- ============================================

ALTER TABLE public.lawyers
  ADD COLUMN IF NOT EXISTS partner_terms jsonb;

ALTER TABLE public.revenue_records
  ADD COLUMN IF NOT EXISTS firm_amount numeric,
  ADD COLUMN IF NOT EXISTS attribution_basis text;

COMMENT ON COLUMN public.lawyers.partner_terms IS
  '合署律師分潤規則（jsonb）。null = 非合署或暫不套用 attribution。';

COMMENT ON COLUMN public.revenue_records.firm_amount IS
  '喆律端應入帳金額（amount 套 partner_terms 後）。null = 未計算或無對應律師。';

COMMENT ON COLUMN public.revenue_records.attribution_basis IS
  '計算依據：self_take / consult_fee / case_close / firm_default / null';

-- 雪莉、昭萱、煜婕：諮詢律師型 70/30
UPDATE public.lawyers SET partner_terms = jsonb_build_object(
  'self_take_firm_pct',              0.30,
  'consult_fee_amount',              2000,
  'consult_fee_firm_pct',            0.00,
  'case_close_firm_pct',             0.95,
  'self_take_includes_consult_fee',  true,
  'monthly_firm_cost',               0,
  'notes',                           '諮詢律師型；自帶承辦 律師70/喆律30；諮詢費100%律師'
) WHERE name IN ('柯雪莉', '李昭萱', '許煜婕');

-- 顯皓：諮詢律師型 60/40，諮詢費歸喆律
UPDATE public.lawyers SET partner_terms = jsonb_build_object(
  'self_take_firm_pct',              0.40,
  'consult_fee_amount',              2000,
  'consult_fee_firm_pct',            1.00,
  'case_close_firm_pct',             0.95,
  'self_take_includes_consult_fee',  false,
  'monthly_firm_cost',               130000,
  'notes',                           '11503起自帶承辦只能≤20萬；獎金率3/5/8%先用5%(0.95)估算；月給律師130000'
) WHERE name = '黃顯皓';
