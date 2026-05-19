-- 把三個 follow-up 欄位從 TEXT 改成 BOOLEAN（改成勾選 vs 填字）
-- 剛加（20260519140000）尚無資料，直接 DROP + ADD 最乾淨

ALTER TABLE public.consultation_cases DROP COLUMN IF EXISTS followup_day;
ALTER TABLE public.consultation_cases DROP COLUMN IF EXISTS followup_week;
ALTER TABLE public.consultation_cases DROP COLUMN IF EXISTS followup_final;

ALTER TABLE public.consultation_cases
  ADD COLUMN followup_day BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN followup_week BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN followup_final BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.consultation_cases.followup_day IS '當天追蹤已完成（勾選）';
COMMENT ON COLUMN public.consultation_cases.followup_week IS '一週追蹤已完成（勾選）';
COMMENT ON COLUMN public.consultation_cases.followup_final IS '最後追蹤已完成（勾選）';
