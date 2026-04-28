-- ============================================================
--  跟進中案件 - 使用者標記狀態（per-client，不被同步覆蓋）
--  目的：讓使用者在 dashboard 標記「是否還需後續追蹤」，
--       避免每日 Apps Script DELETE+INSERT 把標記沖掉。
--  Key: client_name（同一客戶若有兩筆 pending case 共用此狀態）
-- ============================================================

CREATE TABLE IF NOT EXISTS advisor_pending_state (
    client_name    TEXT PRIMARY KEY,
    needs_followup BOOLEAN DEFAULT true,
    updated_at     TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_pending_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_pending_state_select ON advisor_pending_state
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_pending_state_admin ON advisor_pending_state
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
