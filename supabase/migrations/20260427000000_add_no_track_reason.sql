-- 新增「暫不追蹤原因」欄位到 consultation_cases
-- 未成案追蹤頁面讓法務/律師標註某案件暫時不再追蹤的原因（自由文字）

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS no_track_reason TEXT;

COMMENT ON COLUMN public.consultation_cases.no_track_reason IS
  '暫不追蹤原因：法務/律師在未成案追蹤頁面填寫的原因說明（自由文字）';
