-- ============================================
-- consultation_cases 諮詢案件記錄表
-- ============================================

CREATE TABLE IF NOT EXISTS public.consultation_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lawyer_id UUID NOT NULL REFERENCES public.lawyers(id) ON DELETE CASCADE,
  case_date DATE NOT NULL,
  case_type TEXT NOT NULL DEFAULT '',
  case_number TEXT NOT NULL,
  client_name TEXT,
  is_signed BOOLEAN NOT NULL DEFAULT false,
  meeting_record TEXT,
  transcript TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(case_number)
);

CREATE INDEX IF NOT EXISTS idx_cases_lawyer ON public.consultation_cases(lawyer_id);
CREATE INDEX IF NOT EXISTS idx_cases_date ON public.consultation_cases(case_date);

ALTER TABLE public.consultation_cases ENABLE ROW LEVEL SECURITY;

-- 使用 get_my_role() 避免 RLS 遞迴
CREATE POLICY "cases_select" ON public.consultation_cases
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() = 'admin'
  );

CREATE POLICY "cases_modify_admin" ON public.consultation_cases
  FOR ALL USING (public.get_my_role() = 'admin');
