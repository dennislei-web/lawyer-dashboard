-- ============================================================
--  法律顧問 - 系統設定（key/value）
--  目前用途：存 Apps Script Web App URL + sync token
--  其他需要在 dashboard 端「不寫死」的設定也都放這
-- ============================================================

CREATE TABLE IF NOT EXISTS advisor_config (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_config_select ON advisor_config
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_config_admin ON advisor_config
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
