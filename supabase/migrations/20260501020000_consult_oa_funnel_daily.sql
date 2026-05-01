-- ============================================================
--  每日 OA insight 資料（從 LINE Messaging API insight/followers 拉）
--  2026-05-01
--
--  資料延遲：API 約 2 天延遲（最新只到 D-2）
--  欄位定義（依 LINE 官方）：
--    followers        累計曾加入過的人數（含後來封鎖的）
--    targeted_reaches 仍可發送 targeted message 的人 ≈ line.biz 顯示的「好友數」
--    blocks           封鎖人數
-- ============================================================

CREATE TABLE IF NOT EXISTS consult_oa_funnel_daily (
    oa_code           TEXT NOT NULL REFERENCES consult_oa_master(oa_code),
    insight_date      DATE NOT NULL,
    followers         INTEGER,
    targeted_reaches  INTEGER,
    blocks            INTEGER,
    source            TEXT NOT NULL DEFAULT 'line_insight_api',
    ingested_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (oa_code, insight_date)
);

CREATE INDEX IF NOT EXISTS idx_consult_oa_funnel_daily_date
    ON consult_oa_funnel_daily(insight_date);

ALTER TABLE consult_oa_funnel_daily ENABLE ROW LEVEL SECURITY;

CREATE POLICY consult_oa_funnel_daily_select
    ON consult_oa_funnel_daily
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY consult_oa_funnel_daily_admin
    ON consult_oa_funnel_daily
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());


-- ────────────────────────────────────────────────────────────
--  每日新增/淨增（以 LAG 計算前一日差值）
-- ────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_consult_oa_daily_delta AS
SELECT
    d.oa_code,
    o.brand_code,
    o.oa_display_name,
    d.insight_date,
    d.followers,
    d.targeted_reaches,
    d.blocks,
    d.followers
        - LAG(d.followers) OVER w                                AS gross_new_friends,
    d.blocks
        - LAG(d.blocks) OVER w                                   AS new_blocks,
    (d.followers - LAG(d.followers) OVER w)
        - (d.blocks - LAG(d.blocks) OVER w)                      AS net_new_friends,
    d.targeted_reaches
        - LAG(d.targeted_reaches) OVER w                         AS targeted_delta
FROM consult_oa_funnel_daily d
JOIN consult_oa_master o USING (oa_code)
WINDOW w AS (PARTITION BY d.oa_code ORDER BY d.insight_date);


-- ────────────────────────────────────────────────────────────
--  品牌每日彙總（GROUP BY brand）
-- ────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_consult_brand_daily AS
SELECT
    o.brand_code,
    b.display_name           AS brand_name,
    d.insight_date,
    SUM(d.followers)         AS total_followers,
    SUM(d.targeted_reaches)  AS total_targeted,
    SUM(d.blocks)            AS total_blocks,
    COUNT(*)                 AS oa_count
FROM consult_oa_funnel_daily d
JOIN consult_oa_master o USING (oa_code)
JOIN consult_brands b USING (brand_code)
GROUP BY o.brand_code, b.display_name, d.insight_date;
