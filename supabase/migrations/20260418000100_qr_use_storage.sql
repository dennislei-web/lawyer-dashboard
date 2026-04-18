-- ============================================
-- quarterly_reviews 改用 Supabase Storage 存 PDF（而非 base64 塞在 DB）
--   1. 建立 storage bucket 'quarterly-reviews-pdfs'（私有）
--   2. 設定 storage.objects 的 RLS（admin 可寫、律師可讀自己的、admin 可讀全部）
--   3. 調整 quarterly_reviews 表：移除 pdf_base64、新增 file_path
--
-- 路徑慣例：{lawyer_id}/{year}-Q{quarter}.pdf
-- ============================================

-- 1. Storage bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('quarterly-reviews-pdfs', 'quarterly-reviews-pdfs', false)
ON CONFLICT (id) DO NOTHING;

-- 2. Storage RLS policies
-- admin 可對該 bucket 做所有操作
DROP POLICY IF EXISTS "qr_pdf_admin_all" ON storage.objects;
CREATE POLICY "qr_pdf_admin_all" ON storage.objects
  FOR ALL TO authenticated
  USING (bucket_id = 'quarterly-reviews-pdfs' AND public.get_my_role() = 'admin')
  WITH CHECK (bucket_id = 'quarterly-reviews-pdfs' AND public.get_my_role() = 'admin');

-- 律師可讀自己的（路徑以 {lawyer_id}/ 開頭）
DROP POLICY IF EXISTS "qr_pdf_lawyer_read_own" ON storage.objects;
CREATE POLICY "qr_pdf_lawyer_read_own" ON storage.objects
  FOR SELECT TO authenticated
  USING (
    bucket_id = 'quarterly-reviews-pdfs'
    AND (storage.foldername(name))[1] IN (
      SELECT id::text FROM public.lawyers WHERE auth_user_id = auth.uid()
    )
  );

-- 3. 調整 quarterly_reviews 表
-- 舊的 pdf_base64 改為可空（先不 DROP 以免將來要回滾時麻煩，若要完全移除可跑 ALTER TABLE ... DROP COLUMN）
ALTER TABLE public.quarterly_reviews
  ALTER COLUMN pdf_base64 DROP NOT NULL;

ALTER TABLE public.quarterly_reviews
  ADD COLUMN IF NOT EXISTS file_path TEXT;

-- 註：既有資料若有 pdf_base64 內容，可另寫 script 轉到 storage；目前尚無資料所以不用
