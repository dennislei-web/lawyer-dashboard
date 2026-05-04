-- ============================================================
--  3 階段月度漏斗視圖：進線 → 開始訊息 → 約成場次
--  v_consult_oa_3stage_monthly
--
--  進線     = LINE API daily SUM(gross_new_friends)
--  開始訊息 = sheet 月度 leads (consult_oa_monthly_funnel.leads)
--  約成場次 = sheet 月度 sessions
--
--  注意：LINE daily 資料只回 2 天前（D-2），所以「本月」進線
--  數字會 underestimate；建議 dashboard 預設用「上個完整月」
-- ============================================================

CREATE OR REPLACE VIEW v_consult_oa_3stage_monthly AS
WITH daily_agg AS (
    SELECT
        oa_code,
        DATE_TRUNC('month', insight_date)::DATE AS month_start,
        SUM(gross_new_friends) AS line_adds,
        SUM(new_blocks)        AS line_blocks
    FROM v_consult_oa_daily_delta
    WHERE gross_new_friends IS NOT NULL
    GROUP BY oa_code, DATE_TRUNC('month', insight_date)
)
SELECT
    m.oa_code,
    m.brand_code,
    m.oa_display_name,
    m.is_main,
    m.month_start,
    d.line_adds,
    d.line_blocks,
    m.leads    AS messages,        -- sheet「進線」欄位 → 重新命名為「開始訊息」
    m.sessions,
    CASE WHEN COALESCE(d.line_adds, 0) > 0
         THEN ROUND((m.leads::NUMERIC / d.line_adds) * 100, 1)
         ELSE NULL END AS msg_rate,         -- 進線 → 開始訊息 轉換率
    CASE WHEN COALESCE(m.leads, 0) > 0
         THEN ROUND((m.sessions::NUMERIC / m.leads) * 100, 1)
         ELSE NULL END AS sched_rate        -- 開始訊息 → 約成場次 轉換率
FROM v_consult_oa_monthly m
LEFT JOIN daily_agg d USING (oa_code, month_start);


-- 品牌級 3 階段彙總（給 KPI 卡片用）
CREATE OR REPLACE VIEW v_consult_brand_3stage_monthly AS
SELECT
    s.brand_code,
    b.display_name AS brand_name,
    s.month_start,
    SUM(s.line_adds)  AS total_line_adds,
    SUM(s.line_blocks) AS total_line_blocks,
    SUM(s.messages)   AS total_messages,
    SUM(s.sessions)   AS total_sessions,
    CASE WHEN SUM(s.line_adds) > 0
         THEN ROUND((SUM(s.messages)::NUMERIC / SUM(s.line_adds)) * 100, 1)
         ELSE NULL END AS msg_rate,
    CASE WHEN SUM(s.messages) > 0
         THEN ROUND((SUM(s.sessions)::NUMERIC / SUM(s.messages)) * 100, 1)
         ELSE NULL END AS sched_rate,
    COUNT(DISTINCT s.oa_code) AS oa_count
FROM v_consult_oa_3stage_monthly s
JOIN consult_brands b ON b.brand_code = s.brand_code
GROUP BY s.brand_code, b.display_name, s.month_start;
