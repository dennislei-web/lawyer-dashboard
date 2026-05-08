-- ============================================
-- 將營運頁子權限從 revenue_partner 改為 revenue_dept
--
-- 新規則：
--   - 'revenue'      → 看到營運頁全部 tabs
--   - 'revenue_dept' → 只看到「部門分析」tab
--
-- 兩者皆能讀取 revenue_records / monthly_revenue_stats
-- （部門分析也是查同一張表的彙整）
-- ============================================

CREATE OR REPLACE FUNCTION can_view_all_revenue()
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM lawyers
        WHERE auth_user_id = auth.uid()
          AND role = 'manager'
          AND dashboard_access IS NOT NULL
          AND ('revenue' = ANY(dashboard_access)
               OR 'revenue_dept' = ANY(dashboard_access))
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;
