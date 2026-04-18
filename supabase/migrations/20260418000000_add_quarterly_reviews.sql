-- ============================================
-- 1 on 1 會議季度評估 PDF 儲存表
-- 每位律師每季一份 PDF（民國年 + 季度），以 base64 存在 pdf_base64 欄位
-- 建議使用情境：admin 上傳、律師自己可看自己的
-- ============================================

CREATE TABLE IF NOT EXISTS public.quarterly_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lawyer_id UUID NOT NULL REFERENCES public.lawyers(id) ON DELETE CASCADE,
  year INT NOT NULL,                 -- 民國年 (e.g. 115)
  quarter INT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  file_name TEXT,
  file_size INT,
  mime_type TEXT DEFAULT 'application/pdf',
  pdf_base64 TEXT,                   -- base64 編碼的 PDF 內容
  notes TEXT,                        -- 補充備註（可選）
  uploaded_at TIMESTAMPTZ DEFAULT now(),
  uploaded_by UUID REFERENCES auth.users(id),
  UNIQUE (lawyer_id, year, quarter)
);

CREATE INDEX IF NOT EXISTS idx_qr_lawyer ON public.quarterly_reviews(lawyer_id);
CREATE INDEX IF NOT EXISTS idx_qr_yq ON public.quarterly_reviews(year, quarter);

ALTER TABLE public.quarterly_reviews ENABLE ROW LEVEL SECURITY;

-- 律師可看自己的 + admin 可看全部
DROP POLICY IF EXISTS "qr_select" ON public.quarterly_reviews;
CREATE POLICY "qr_select" ON public.quarterly_reviews
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() = 'admin'
  );

-- 只有 admin 可以寫入/更新/刪除
DROP POLICY IF EXISTS "qr_modify_admin" ON public.quarterly_reviews;
CREATE POLICY "qr_modify_admin" ON public.quarterly_reviews
  FOR ALL USING (public.get_my_role() = 'admin');
