-- ============================================================
--  會議追蹤 ─ Schema
--  目的：解決「會議事項一直 carry over 沒人結」問題
--    每次營運會議產生 / 追蹤 / 結案的 action items 變結構化資料
--    可以選擇綁 OKR KR 也可純組織管理
--  前置：lawyers, is_admin(), update_updated_at_column()
-- ============================================================

-- 1. 會議：每次股東 / 營運 / 月會一筆
CREATE TABLE IF NOT EXISTS meetings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_date  DATE NOT NULL,
    meeting_type  TEXT NOT NULL DEFAULT 'op_weekly'
                  CHECK (meeting_type IN ('op_weekly','shareholder','monthly_all','partner_consult','one_on_one','other')),
    title         TEXT,
    attendees     TEXT[],
    source_url    TEXT,
    summary       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    updated_by    UUID REFERENCES lawyers(id),
    UNIQUE (meeting_date, meeting_type)
);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date DESC);

DROP TRIGGER IF EXISTS meetings_updated_at ON meetings;
CREATE TRIGGER meetings_updated_at
    BEFORE UPDATE ON meetings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 2. 行動項目：每個待辦 / 追蹤事項；可選綁 KR
CREATE TABLE IF NOT EXISTS meeting_action_items (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_meeting_id  UUID REFERENCES meetings(id) ON DELETE SET NULL,
    title              TEXT NOT NULL,
    category           TEXT,    -- 法律010 / 工程 / 合署 / 客戶關係 / 法顧 / 人資 / 財務 / 其他
    kr_code            TEXT,    -- kr1..kr7 或 NULL = 純組織管理
    owner              TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','in_progress','blocked','done','dropped')),
    due_date           DATE,
    next_review_date   DATE,
    carry_count        INTEGER NOT NULL DEFAULT 1,   -- 出現在幾場會議
    latest_resolution  TEXT,    -- 最新一次 follow-up 摘要
    notes              TEXT,
    closed_at          TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now(),
    updated_by         UUID REFERENCES lawyers(id)
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON meeting_action_items(status);
CREATE INDEX IF NOT EXISTS idx_actions_kr     ON meeting_action_items(kr_code);
CREATE INDEX IF NOT EXISTS idx_actions_owner  ON meeting_action_items(owner);
CREATE INDEX IF NOT EXISTS idx_actions_review ON meeting_action_items(next_review_date);

DROP TRIGGER IF EXISTS actions_updated_at ON meeting_action_items;
CREATE TRIGGER actions_updated_at
    BEFORE UPDATE ON meeting_action_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 3. 追蹤紀錄：每次會議對某 action 的 follow-up
CREATE TABLE IF NOT EXISTS action_followups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id  UUID NOT NULL REFERENCES meeting_action_items(id) ON DELETE CASCADE,
    meeting_id      UUID REFERENCES meetings(id) ON DELETE SET NULL,
    followup_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    status_before   TEXT,
    status_after    TEXT,
    resolution      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    created_by      UUID REFERENCES lawyers(id)
);
CREATE INDEX IF NOT EXISTS idx_followups_action ON action_followups(action_item_id, followup_date DESC);
CREATE INDEX IF NOT EXISTS idx_followups_meeting ON action_followups(meeting_id);

-- ============================================================
--  RLS：admin only（跟 okr_* tables 一致）
-- ============================================================
ALTER TABLE meetings              ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_action_items  ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_followups      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meetings_admin            ON meetings;
DROP POLICY IF EXISTS meeting_actions_admin     ON meeting_action_items;
DROP POLICY IF EXISTS action_followups_admin    ON action_followups;

CREATE POLICY meetings_admin
    ON meetings FOR ALL
    USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY meeting_actions_admin
    ON meeting_action_items FOR ALL
    USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY action_followups_admin
    ON action_followups FOR ALL
    USING (is_admin()) WITH CHECK (is_admin());
