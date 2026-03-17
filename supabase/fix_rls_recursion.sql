-- ============================================
-- 修正 lawyers 表 RLS 無限遞迴問題
-- 原因：lawyers_select_view_all 政策在 lawyers 表上
--       使用子查詢查 lawyers 表本身，造成無限遞迴
-- 修正：改用 SECURITY DEFINER 函數繞過 RLS
-- ============================================

-- 1. 建立 SECURITY DEFINER 函數（繞過 RLS 檢查）
CREATE OR REPLACE FUNCTION public.can_view_all()
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.lawyers
    WHERE auth_user_id = auth.uid() AND can_view_all = true
  );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- 2. 刪除造成無限遞迴的舊政策
DROP POLICY IF EXISTS "lawyers_select_view_all" ON public.lawyers;

-- 3. 重建 lawyers 表的 can_view_all 政策（使用函數）
CREATE POLICY "lawyers_select_view_all" ON public.lawyers
  FOR SELECT USING (public.can_view_all());

-- 4. 修正 monthly_stats 政策（也改用函數，避免間接遞迴）
DROP POLICY IF EXISTS "monthly_stats_select_view_all" ON public.monthly_stats;
CREATE POLICY "monthly_stats_select_view_all" ON public.monthly_stats
  FOR SELECT USING (public.can_view_all());

-- 5. 修正 consultation_cases 政策
DROP POLICY IF EXISTS "cases_select" ON public.consultation_cases;
CREATE POLICY "cases_select" ON public.consultation_cases
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() = 'admin'
    OR public.can_view_all()
  );

-- 6. 修正 consultation_logs 政策
DROP POLICY IF EXISTS "consultation_logs_select_view_all" ON public.consultation_logs;
CREATE POLICY "consultation_logs_select_view_all" ON public.consultation_logs
  FOR SELECT USING (public.can_view_all());
