-- ============================================================
--  月度場次/進線 視圖（給 funnel 頁的「月場次 / 進線」section 用）
-- ============================================================

-- OA 級月度明細 + 預先計算約成率
CREATE OR REPLACE VIEW v_consult_oa_monthly AS
SELECT
    m.oa_code,
    o.brand_code,
    o.oa_display_name,
    o.is_main,
    m.month_start,
    m.sessions,
    m.leads,
    CASE WHEN m.leads > 0
         THEN ROUND((m.sessions::NUMERIC / m.leads) * 100, 1)
         ELSE NULL END AS sched_pct
FROM consult_oa_monthly_funnel m
JOIN consult_oa_master o USING (oa_code)
WHERE o.status = 'active';

-- 品牌級月度匯總
CREATE OR REPLACE VIEW v_consult_brand_monthly AS
SELECT
    o.brand_code,
    b.display_name AS brand_name,
    m.month_start,
    SUM(m.sessions) AS total_sessions,
    SUM(m.leads) AS total_leads,
    CASE WHEN SUM(m.leads) > 0
         THEN ROUND((SUM(m.sessions)::NUMERIC / SUM(m.leads)) * 100, 1)
         ELSE NULL END AS sched_pct,
    COUNT(*) AS oa_count
FROM consult_oa_monthly_funnel m
JOIN consult_oa_master o USING (oa_code)
JOIN consult_brands b ON b.brand_code = o.brand_code
WHERE o.status = 'active'
GROUP BY o.brand_code, b.display_name, m.month_start;
