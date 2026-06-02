-- ============================================================
--  meeting_action_items：加 recur_type
--    oneoff  = 一次性（做完即結案）
--    ongoing = 持續關注（成效/累積型，不會結案，固定週期 review）
--  目的：OKR 頁可篩掉 ongoing，待辦區只留「要動作」的一次性
-- ============================================================
ALTER TABLE meeting_action_items
    ADD COLUMN IF NOT EXISTS recur_type TEXT NOT NULL DEFAULT 'oneoff'
    CHECK (recur_type IN ('oneoff','ongoing'));

CREATE INDEX IF NOT EXISTS idx_actions_recur ON meeting_action_items(recur_type);

-- 標記目前 2 個持續關注型
UPDATE meeting_action_items
SET recur_type = 'ongoing'
WHERE title IN (
    '里長線下諮詢 ─ 目標帶 160 場諮詢',
    '短影音廣告成效'
);
