-- ============================================================
--  LINE OA 憑證表 + 補上 14 個 channel ID
--  2026-05-01
--
--  說明：
--   1. 把已盤點到的 14 個 LINE Channel ID 寫進 consult_oa_master
--      (FA 之前已知 2008600392；其餘 13 個今日批次開通取得)
--   2. 新增 consult_oa_credentials 表存 access token
--      RLS 故意只讓 service_role 讀寫，避免從 dashboard 端誤讀
-- ============================================================

-- ── 1. 更新 line_oa_id 到 consult_oa_master ──

UPDATE consult_oa_master SET line_oa_id = '2008600392' WHERE oa_code = 'FA';
UPDATE consult_oa_master SET line_oa_id = '2009947818' WHERE oa_code = '1FA';
UPDATE consult_oa_master SET line_oa_id = '2009947793' WHERE oa_code = '2FA';
UPDATE consult_oa_master SET line_oa_id = '2009947783' WHERE oa_code = '3FA';
UPDATE consult_oa_master SET line_oa_id = '2009947764' WHERE oa_code = '4FA';
UPDATE consult_oa_master SET line_oa_id = '2009947757' WHERE oa_code = '5FA';
UPDATE consult_oa_master SET line_oa_id = '2009947740' WHERE oa_code = '6FA';
UPDATE consult_oa_master SET line_oa_id = '2009879367' WHERE oa_code = 'MB';
UPDATE consult_oa_master SET line_oa_id = '2009947806' WHERE oa_code = '1MB';
UPDATE consult_oa_master SET line_oa_id = '2009947787' WHERE oa_code = '2MB';
UPDATE consult_oa_master SET line_oa_id = '2009947772' WHERE oa_code = '3MB';
UPDATE consult_oa_master SET line_oa_id = '2009947670' WHERE oa_code = '4MB';
UPDATE consult_oa_master SET line_oa_id = '2009947839' WHERE oa_code = 'Z';
UPDATE consult_oa_master SET line_oa_id = '2009947876' WHERE oa_code = '1Z';
-- FL（FastLaw法速答）不在 zhelu-product Provider，第一階段擱置；
-- 之前以為 channel id 是 2006703271 但那其實是「法律 FOLLOW ME」的，已修正
UPDATE consult_oa_master
SET line_oa_id = NULL,
    status = 'paused',
    notes = 'FastLaw 在另一個 Provider，待行政取得權限後再追蹤'
WHERE oa_code = 'FL';

-- ── 2. 憑證表 ──

CREATE TABLE IF NOT EXISTS consult_oa_credentials (
    oa_code              TEXT PRIMARY KEY REFERENCES consult_oa_master(oa_code),
    line_channel_id      TEXT NOT NULL,
    line_channel_token   TEXT,                    -- 可空，等 issue 完才填
    issued_at            TIMESTAMPTZ,
    last_rotated_at      TIMESTAMPTZ,
    notes                TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE consult_oa_credentials ENABLE ROW LEVEL SECURITY;

-- 故意不寫 SELECT policy；只有 service_role 能透過 admin 規則讀寫
CREATE POLICY consult_oa_creds_admin
    ON consult_oa_credentials
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

-- 預先把 14 個 channel id 種進去（token 待後續 import 補）
INSERT INTO consult_oa_credentials (oa_code, line_channel_id) VALUES
    ('FA',  '2008600392'),
    ('1FA', '2009947818'),
    ('2FA', '2009947793'),
    ('3FA', '2009947783'),
    ('4FA', '2009947764'),
    ('5FA', '2009947757'),
    ('6FA', '2009947740'),
    ('MB',  '2009879367'),
    ('1MB', '2009947806'),
    ('2MB', '2009947787'),
    ('3MB', '2009947772'),
    ('4MB', '2009947670'),
    ('Z',   '2009947839'),
    ('1Z',  '2009947876')
    -- FL 暫時不種，等 FastLaw 取得權限後再補
ON CONFLICT (oa_code) DO UPDATE SET
    line_channel_id = EXCLUDED.line_channel_id,
    updated_at = now();
