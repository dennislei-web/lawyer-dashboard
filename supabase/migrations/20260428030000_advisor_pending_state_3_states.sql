-- ============================================================
--  跟進中案件 - 後續追蹤狀態改 3 值
--  從 needs_followup boolean 改成 followup_status text
--  （前一個 migration 才剛建表、資料量極小，直接 DROP 重建）
-- ============================================================

DROP TABLE IF EXISTS advisor_pending_state CASCADE;

CREATE TABLE advisor_pending_state (
    client_name     TEXT PRIMARY KEY,
    followup_status TEXT DEFAULT '持續追蹤' CHECK (followup_status IN ('持續追蹤','暫時等待','無須追蹤')),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_pending_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_pending_state_select ON advisor_pending_state
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_pending_state_admin ON advisor_pending_state
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
