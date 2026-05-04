-- ============================================================
--  consult_oa_tag_chats_monthly
--
--  資料源：LINE OA Manager 後台 → 聊天設定 → 標籤 → 「YY年MM月」
--          標籤底下的「聊天室數量」= 該月新打標的聊天室數
--          ≈ 該月真正開始 1-on-1 對話的用戶數
--
--  為何另開一張表（而不是加欄到 consult_oa_monthly_funnel）：
--  - 寫入來源不同（admin UI manual entry vs Apps Script ETL）
--  - 避免 Apps Script UPSERT 時把 admin 填的數字洗掉
--  - 容易單獨稽核「誰、何時、改成多少」
--
--  填法：dashboard /funnel 頁的 admin only 「✏️ 編輯訊息」按鈕
-- ============================================================

-- 視圖必須先 DROP（manual_adds 欄插在中間，CREATE OR REPLACE 會踩 column rename 限制）
DROP VIEW IF EXISTS v_consult_brand_3stage_monthly;
DROP VIEW IF EXISTS v_consult_oa_3stage_monthly;

CREATE TABLE IF NOT EXISTS consult_oa_tag_chats_monthly (
    oa_code      TEXT NOT NULL REFERENCES consult_oa_master(oa_code),
    month_start  DATE NOT NULL,
    chat_rooms   INT  NOT NULL CHECK (chat_rooms >= 0),
    source       TEXT DEFAULT 'admin_ui',
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_by   UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (oa_code, month_start),
    CONSTRAINT month_start_is_first CHECK (EXTRACT(DAY FROM month_start) = 1)
);

CREATE INDEX IF NOT EXISTS consult_oa_tag_chats_month_idx ON consult_oa_tag_chats_monthly (month_start DESC, oa_code);

ALTER TABLE consult_oa_tag_chats_monthly ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS consult_oa_tag_chats_select ON consult_oa_tag_chats_monthly;
DROP POLICY IF EXISTS consult_oa_tag_chats_admin  ON consult_oa_tag_chats_monthly;
CREATE POLICY consult_oa_tag_chats_select ON consult_oa_tag_chats_monthly FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_oa_tag_chats_admin  ON consult_oa_tag_chats_monthly FOR ALL    USING (is_admin()) WITH CHECK (is_admin());

-- ============================================================
--  v_consult_oa_3stage_monthly  (重建)
--
--  ① line_adds   = LINE Messaging API 加好友 (D-2 即時)
--  ② messages    = OA 標籤聊天室數 (admin UI, 月底人工填)
--  ③ sessions    = sheet「各帳號統計」場次 (Apps Script 週同步)
--
--  manual_adds   = sheet「各帳號統計」進線 (Apps Script 週同步, 與 ② 不再混用)
--                  保留作為與 LINE API 對照的歷史資料
-- ============================================================

CREATE VIEW v_consult_oa_3stage_monthly AS
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
    t.chat_rooms        AS messages,        -- ② 來自 OA 標籤
    m.leads             AS manual_adds,     -- 對照用：sheet 人工統計的「進線」
    m.sessions,
    CASE WHEN COALESCE(d.line_adds, 0) > 0 AND t.chat_rooms IS NOT NULL
         THEN ROUND((t.chat_rooms::NUMERIC / d.line_adds) * 100, 1)
         ELSE NULL END AS msg_rate,
    CASE WHEN COALESCE(t.chat_rooms, 0) > 0
         THEN ROUND((m.sessions::NUMERIC / t.chat_rooms) * 100, 1)
         ELSE NULL END AS sched_rate
FROM v_consult_oa_monthly m
LEFT JOIN daily_agg d                      USING (oa_code, month_start)
LEFT JOIN consult_oa_tag_chats_monthly t   USING (oa_code, month_start);


CREATE VIEW v_consult_brand_3stage_monthly AS
SELECT
    s.brand_code,
    b.display_name AS brand_name,
    s.month_start,
    SUM(s.line_adds)    AS total_line_adds,
    SUM(s.line_blocks)  AS total_line_blocks,
    SUM(s.messages)     AS total_messages,
    SUM(s.manual_adds)  AS total_manual_adds,
    SUM(s.sessions)     AS total_sessions,
    CASE WHEN SUM(s.line_adds) > 0 AND SUM(s.messages) IS NOT NULL
         THEN ROUND((SUM(s.messages)::NUMERIC / SUM(s.line_adds)) * 100, 1)
         ELSE NULL END AS msg_rate,
    CASE WHEN COALESCE(SUM(s.messages), 0) > 0
         THEN ROUND((SUM(s.sessions)::NUMERIC / SUM(s.messages)) * 100, 1)
         ELSE NULL END AS sched_rate,
    COUNT(DISTINCT s.oa_code) AS oa_count
FROM v_consult_oa_3stage_monthly s
JOIN consult_brands b ON b.brand_code = s.brand_code
GROUP BY s.brand_code, b.display_name, s.month_start;
