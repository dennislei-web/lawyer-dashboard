-- ============================================
-- 遷移：consultation_cases 加入 revenue, collected 欄位
-- 用於成案金額區間分析
-- ============================================

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS revenue NUMERIC(12,0) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS collected NUMERIC(12,0) DEFAULT 0;
