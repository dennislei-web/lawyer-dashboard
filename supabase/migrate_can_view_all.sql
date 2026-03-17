-- ============================================
-- 新增 can_view_all 欄位到 lawyers 表
-- 管理員可控制哪些律師能看到全部資料
-- ============================================

-- 1. 新增欄位
ALTER TABLE public.lawyers
  ADD COLUMN IF NOT EXISTS can_view_all BOOLEAN DEFAULT false;

-- 2. 更新 RLS 政策：允許 can_view_all=true 的律師看全部資料

-- ----- lawyers 表 -----
-- 新增：can_view_all 的律師可以看到所有律師
CREATE POLICY "lawyers_select_view_all" ON public.lawyers
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.can_view_all = true
    )
  );

-- ----- monthly_stats 表 -----
-- 新增：can_view_all 的律師可以看全部月統計
CREATE POLICY "monthly_stats_select_view_all" ON public.monthly_stats
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );

-- ----- consultation_cases 表 -----
-- 需要先 DROP 再重建 cases_select，因為要加入 can_view_all 條件
DROP POLICY IF EXISTS "cases_select" ON public.consultation_cases;
CREATE POLICY "cases_select" ON public.consultation_cases
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() = 'admin'
    OR EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );

-- ----- consultation_logs 表 -----
-- 新增：can_view_all 的律師可以看全部諮詢記錄
CREATE POLICY "consultation_logs_select_view_all" ON public.consultation_logs
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );

-- 3. 允許管理員更新 can_view_all 欄位（已有 lawyers_update_admin 政策，無需額外新增）
