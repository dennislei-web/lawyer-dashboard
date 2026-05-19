-- 未成案追蹤：新增「律師補充」欄位
--
-- 背景：諮詢後速記 (tracking_notes) 每天從 CRM 同步覆寫，律師若直接編輯會被蓋掉。
-- 新增獨立欄位 lawyer_tracking_notes，律師可在前端表格 inline 編輯，永久保留。

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS lawyer_tracking_notes TEXT;

COMMENT ON COLUMN public.consultation_cases.lawyer_tracking_notes IS
  '律師對諮詢後速記的補充內容，不會被 CRM 同步覆寫';
