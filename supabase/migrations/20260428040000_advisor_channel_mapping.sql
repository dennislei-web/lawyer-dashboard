-- ============================================================
--  跟進中案件 - 管道來源分類映射
--  raw_channel：Sheet 端原始填寫的內容（可能拼寫不一致、過於細）
--  canonical：使用者手動歸類後的標準分類；null = 歸到「其他」
-- ============================================================

CREATE TABLE IF NOT EXISTS advisor_channel_mapping (
    raw_channel TEXT PRIMARY KEY,
    canonical   TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_channel_mapping ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_channel_mapping_select ON advisor_channel_mapping
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_channel_mapping_admin ON advisor_channel_mapping
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
