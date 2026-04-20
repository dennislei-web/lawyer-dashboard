-- ============================================
-- lawyers 表新增 admin 的 INSERT RLS policy
-- 之前只有 SELECT 和 UPDATE，INSERT 被擋 → admin 從 UI 建新帳號失敗
-- ============================================

DROP POLICY IF EXISTS "lawyers_insert_admin" ON public.lawyers;

CREATE POLICY "lawyers_insert_admin" ON public.lawyers
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.role = 'admin'
    )
  );

-- 允許 admin 刪除 lawyers（未來若要移除錯建的帳號）
DROP POLICY IF EXISTS "lawyers_delete_admin" ON public.lawyers;

CREATE POLICY "lawyers_delete_admin" ON public.lawyers
  FOR DELETE USING (
    EXISTS (
      SELECT 1 FROM public.lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.role = 'admin'
    )
  );
