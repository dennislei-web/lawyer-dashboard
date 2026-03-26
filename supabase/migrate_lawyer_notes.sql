-- 新增律師追蹤建議欄位
ALTER TABLE public.consultation_cases ADD COLUMN IF NOT EXISTS lawyer_notes TEXT;

-- RLS: 允許已登入使用者更新 consultation_cases（前端只送 lawyer_notes）
DROP POLICY IF EXISTS "cases_update_notes" ON public.consultation_cases;
CREATE POLICY "cases_update_notes" ON public.consultation_cases
  FOR UPDATE USING (true) WITH CHECK (true);
