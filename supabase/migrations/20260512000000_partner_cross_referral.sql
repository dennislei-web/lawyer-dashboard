-- ============================================
-- 合署跨轉案件 (partner cross referral)
--
-- 解決問題：北所/中所諮詢律師諮詢後，案件轉給合署律師承辦。
-- 結果：
--   - consultation_cases 端：諮詢 +1、成案 +1（諮詢律師在北所/中所）
--   - revenue_records 端：group_name 含「合署」，被 excludePartner() 過濾掉
--   - 北所/中所部門分析的 CRM 付款金額 = 0（喆律端實際入帳 firm_amount 沒被歸到分所）
--
-- 此表把合署 CSV (senior_profit_share.csv tier='喆律轉案') 中的跨轉案
-- 反推到 consultation_cases，補回「諮詢律師端應看到的合署端進帳」KPI。
--
-- 第一版只做：方向 'out' (北所/中所→合署)，來源 senior cohort tier='喆律轉案'
-- 暫不做：'in' 方向（資料雜訊重）、judicial cohort（量小且無 client 欄位）
-- ============================================

CREATE TABLE IF NOT EXISTS public.partner_cross_referral (
  id BIGSERIAL PRIMARY KEY,

  -- 案件期間（民國年，跟合署 CSV 一致）
  year INT NOT NULL,
  month INT NOT NULL,

  -- 方向：'out' = 諮詢律師→合署承辦；'in' = 合署諮詢→外部承辦
  direction TEXT NOT NULL CHECK (direction IN ('out', 'in')),

  -- 合署律師（承辦方）
  partner_lawyer_name TEXT NOT NULL,
  partner_lawyer_id UUID REFERENCES public.lawyers(id),
  partner_cohort TEXT NOT NULL CHECK (partner_cohort IN ('senior', 'judicial')),

  -- 案件
  client_name TEXT NOT NULL,
  case_amount NUMERIC,           -- 案件總金額
  firm_amount NUMERIC,           -- 喆律端應入帳（zhelu_amt）
  lawyer_amount NUMERIC,         -- 合署律師端入帳（lawyer_amt）
  raw_tier TEXT NOT NULL,        -- 原 tier 名稱（喆律轉案 / 成案獎金 / ...）

  -- 反推 join 結果（找不到對應的諮詢記錄時為 null）
  referring_lawyer_id UUID REFERENCES public.lawyers(id),
  consultation_case_id UUID REFERENCES public.consultation_cases(id),
  join_quality TEXT,             -- 'exact' (唯一命中) / 'nearest' (多筆取最近) / 'none' (找不到)

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 避免重複 upsert（同合署律師、同月、同 client、同金額、同 tier 視為同一筆）
-- 注意：PostgREST on_conflict 不支援 expression index，故 case_amount 直接用欄位
-- （CSV 來源每筆都有金額，case_amount NULL 機率極低）
CREATE UNIQUE INDEX IF NOT EXISTS uniq_partner_cross_referral
  ON public.partner_cross_referral(
    partner_lawyer_name, year, month, client_name, raw_tier, case_amount
  );

CREATE INDEX IF NOT EXISTS idx_pcr_referring_lawyer
  ON public.partner_cross_referral(referring_lawyer_id, year, month);

CREATE INDEX IF NOT EXISTS idx_pcr_direction_year
  ON public.partner_cross_referral(direction, year, month);

-- RLS：跟 revenue_records 一致，admin 才可讀寫
ALTER TABLE public.partner_cross_referral ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pcr_admin_all" ON public.partner_cross_referral
  FOR ALL USING (public.get_my_role() = 'admin');

COMMENT ON TABLE public.partner_cross_referral IS
  '合署跨轉案件（CSV → ETL 反推），補正部門分析的 CRM 收款口徑';
COMMENT ON COLUMN public.partner_cross_referral.firm_amount IS
  '喆律端應入帳金額；用於 /revenue 部門分析新 KPI「合署端進帳（諮詢律師轉入）」';
COMMENT ON COLUMN public.partner_cross_referral.referring_lawyer_id IS
  '反推自 consultation_cases.lawyer_id（用 client_name + 最近 case_date）；null = 找不到對應諮詢記錄';
