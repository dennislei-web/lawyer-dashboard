-- ============================================
-- 讓 manager 透過 dashboard_access 取得 revenue_records / monthly_revenue_stats 讀取權限
--
-- 背景：
--   原本 RLS 政策只允許 admin 與「department_members」中的成員讀取營收資料；
--   但管理介面已開放「dashboard_access 勾選營運」就能進營運頁，後端卻沒授權，
--   導致 manager 進到頁面但看到空資料。
--
-- 規則：
--   - admin                              → 全部
--   - manager 且 dashboard_access 含
--     'revenue' 或 'revenue_partner'     → 全部
--   - 其餘                                → 仍依部門成員身分過濾
-- ============================================

CREATE OR REPLACE FUNCTION can_view_all_revenue()
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM lawyers
        WHERE auth_user_id = auth.uid()
          AND role = 'manager'
          AND dashboard_access IS NOT NULL
          AND ('revenue' = ANY(dashboard_access)
               OR 'revenue_partner' = ANY(dashboard_access))
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

DROP POLICY IF EXISTS revenue_select ON revenue_records;
CREATE POLICY revenue_select ON revenue_records
    FOR SELECT USING (
        is_admin()
        OR can_view_all_revenue()
        OR department_id IN (SELECT get_my_department_ids())
    );

DROP POLICY IF EXISTS monthly_revenue_select ON monthly_revenue_stats;
CREATE POLICY monthly_revenue_select ON monthly_revenue_stats
    FOR SELECT USING (
        is_admin()
        OR can_view_all_revenue()
        OR department_id IN (SELECT get_my_department_ids())
    );
