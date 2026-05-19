-- 未成案追蹤：新增三個 follow-up 階段欄位
--
-- 當天追蹤 / 一週追蹤 / 最後追蹤
-- 法務在「未成案追蹤」表內 inline 編輯，記錄每階段的追單動作與結果

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS followup_day TEXT,
  ADD COLUMN IF NOT EXISTS followup_week TEXT,
  ADD COLUMN IF NOT EXISTS followup_final TEXT;

COMMENT ON COLUMN public.consultation_cases.followup_day IS '當天追蹤紀錄（法務 inline 編輯）';
COMMENT ON COLUMN public.consultation_cases.followup_week IS '一週追蹤紀錄（法務 inline 編輯）';
COMMENT ON COLUMN public.consultation_cases.followup_final IS '最後追蹤紀錄（法務 inline 編輯）';
