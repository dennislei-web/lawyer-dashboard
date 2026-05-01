-- ============================================================
--  委前諮詢漏斗（consultation funnel）— 第一階段資料模型
--
--  範圍：4 大品牌 × 13 個被追蹤的 LINE OA
--    85010    : FA, 1FA~6FA  (主號 + 6 個 Clone)
--    金貝殼   : MB, 1MB~4MB  (主號 + 4 個 Clone)
--    吉他     : Z, 1Z         (主 + 副)
--    FastLaw  : FL            (單一)
--
--  資料來源：Google Sheets「委前各項數據追蹤表單」
--    - 各帳號進線及場次數據統計表 → consult_oa_monthly_funnel
--    - BI                          → consult_brand_monthly_outcomes
--    - 個人場次2025/2026           → consult_staff_monthly_sessions
--    - 追蹤記錄表                  → consult_consultations
--    - 臨陣脫逃紀錄表              → consult_no_shows
--    - 進線至匯款日數統計          → consult_conversion_cycles
--
--  時間維度：
--    所有時間欄統一用「西元」+ DATE，YYYY-MM-01 表示月份起始日
--    來源 sheet 用 ROC（民國 114 = 西元 2025），由 ETL 層轉換
--
--  名稱慣例：
--    與既有 advisor_* / consultation_* 並列，使用 consult_* 前綴
-- ============================================================


-- ────────────────────────────────────────────────────────────
--  1. 維度表
-- ────────────────────────────────────────────────────────────

-- 品牌主檔（4 筆）
CREATE TABLE IF NOT EXISTS consult_brands (
    brand_code      TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    category        TEXT,                    -- '綜合' | '債務催收' | '免費諮詢' | etc
    is_active       BOOL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- LINE OA 主檔（13~14 筆 + 預留擴充）
CREATE TABLE IF NOT EXISTS consult_oa_master (
    oa_code         TEXT PRIMARY KEY,        -- 'FA', '1FA', ..., 'MB', '1MB', ..., 'Z', '1Z', 'FL'
    brand_code      TEXT NOT NULL REFERENCES consult_brands(brand_code),
    oa_display_name TEXT NOT NULL,           -- LINE manager 上的完整名稱
    is_main         BOOL NOT NULL DEFAULT FALSE,
    slash_pattern   TEXT,                    -- '/', '//', '\', '\\\', '🐝' 等識別碼
    line_oa_id      TEXT,                    -- LINE Messaging API 的 channel id（之後拉 API 用）
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'retired')),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_consult_oa_master_brand
    ON consult_oa_master(brand_code);


-- 法務人員主檔（委前法務 + 主管）
CREATE TABLE IF NOT EXISTS consult_staff (
    staff_id        SERIAL PRIMARY KEY,
    display_name    TEXT NOT NULL UNIQUE,    -- '蔡宛陵', '林雨辰', '郭玟樺', ...
    role            TEXT,                    -- '委前法務' | '主管' | etc
    is_active       BOOL NOT NULL DEFAULT TRUE,
    start_date      DATE,
    end_date        DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);


-- ────────────────────────────────────────────────────────────
--  2. 月度事實表（aggregate, 從 sheet ETL）
-- ────────────────────────────────────────────────────────────

-- OA 級月度漏斗（進線 + 約成）
-- 來源：各帳號進線及場次數據統計表
CREATE TABLE IF NOT EXISTS consult_oa_monthly_funnel (
    oa_code         TEXT NOT NULL REFERENCES consult_oa_master(oa_code),
    month_start     DATE NOT NULL
                    CHECK (month_start = date_trunc('month', month_start)::DATE),
    leads           INTEGER NOT NULL DEFAULT 0,    -- 月進線數
    sessions        INTEGER NOT NULL DEFAULT 0,    -- 約成現場場次
    -- conversion_rate 用 view 計算，不存
    source          TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (oa_code, month_start)
);

CREATE INDEX IF NOT EXISTS idx_consult_oa_funnel_month
    ON consult_oa_monthly_funnel(month_start);


-- 品牌級月度結果（諮詢、匯款、轉出）
-- 來源：BI sheet
CREATE TABLE IF NOT EXISTS consult_brand_monthly_outcomes (
    brand_code              TEXT NOT NULL REFERENCES consult_brands(brand_code),
    month_start             DATE NOT NULL
                            CHECK (month_start = date_trunc('month', month_start)::DATE),
    consultations           INTEGER,                    -- 諮詢場次（到場）
    signed_cases            INTEGER,                    -- 匯款（成案）
    transferred_to_010      INTEGER,                    -- 轉至法律010（outbound）
    source                  TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at             TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (brand_code, month_start)
);


-- 法務人員月場次
-- 來源：個人場次 2025 / 2026
CREATE TABLE IF NOT EXISTS consult_staff_monthly_sessions (
    staff_id        INTEGER NOT NULL REFERENCES consult_staff(staff_id),
    month_start     DATE NOT NULL
                    CHECK (month_start = date_trunc('month', month_start)::DATE),
    sessions        INTEGER NOT NULL DEFAULT 0,
    signed_count    INTEGER,
    signed_rate     NUMERIC(5,2),
    source          TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (staff_id, month_start)
);

CREATE INDEX IF NOT EXISTS idx_consult_staff_sessions_month
    ON consult_staff_monthly_sessions(month_start);


-- ────────────────────────────────────────────────────────────
--  3. 逐筆事實表
-- ────────────────────────────────────────────────────────────

-- 線上法諮逐筆（追蹤記錄表 ETL；目前 ~18 active items）
CREATE TABLE IF NOT EXISTS consult_consultations (
    id              BIGSERIAL PRIMARY KEY,
    month_start     DATE,                    -- 來自 ROC 年月，ETL 時轉換
    brand_code      TEXT REFERENCES consult_brands(brand_code),     -- 從「品牌」欄（諮詢主題）
    oa_code         TEXT REFERENCES consult_oa_master(oa_code),     -- 從「帳號」欄（進線來源）
    client_name     TEXT,
    consult_date    DATE,
    filled_by       INTEGER REFERENCES consult_staff(staff_id),     -- 填寫人員
    assigned_to     INTEGER REFERENCES consult_staff(staff_id),     -- 追蹤人員
    needs_call      BOOL,
    is_completed    BOOL,
    notes           TEXT,
    source_row_hash TEXT,                                            -- 偵測 sheet 變動
    source          TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_consult_consultations_oa
    ON consult_consultations(oa_code);
CREATE INDEX IF NOT EXISTS idx_consult_consultations_brand
    ON consult_consultations(brand_code);
CREATE INDEX IF NOT EXISTS idx_consult_consultations_date
    ON consult_consultations(consult_date);


-- 沒到場（臨陣脫逃紀錄表）
CREATE TABLE IF NOT EXISTS consult_no_shows (
    id              BIGSERIAL PRIMARY KEY,
    oa_code         TEXT REFERENCES consult_oa_master(oa_code),
    brand_code      TEXT REFERENCES consult_brands(brand_code),
    scheduled_date  DATE,
    client_name     TEXT,
    reason          TEXT,
    source          TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at     TIMESTAMPTZ DEFAULT now()
);


-- 進線→匯款 cycle time（進線至匯款日數統計）
CREATE TABLE IF NOT EXISTS consult_conversion_cycles (
    brand_code      TEXT NOT NULL REFERENCES consult_brands(brand_code),
    month_start     DATE NOT NULL
                    CHECK (month_start = date_trunc('month', month_start)::DATE),
    avg_days        NUMERIC(6,2),
    median_days     NUMERIC(6,2),
    sample_size     INTEGER,
    source          TEXT NOT NULL DEFAULT 'sheet_etl',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (brand_code, month_start)
);


-- ────────────────────────────────────────────────────────────
--  4. 視圖（dashboard 直接查詢）
-- ────────────────────────────────────────────────────────────

-- OA 級漏斗（含轉換率）
CREATE OR REPLACE VIEW v_consult_oa_funnel AS
SELECT
    o.brand_code,
    b.display_name              AS brand_name,
    o.oa_code,
    o.oa_display_name,
    o.is_main,
    f.month_start,
    f.leads,
    f.sessions,
    CASE WHEN f.leads > 0
         THEN ROUND((f.sessions::NUMERIC / f.leads) * 100, 2)
         ELSE NULL END          AS lead_to_session_pct
FROM consult_oa_master o
JOIN consult_brands b USING (brand_code)
LEFT JOIN consult_oa_monthly_funnel f USING (oa_code);

-- 品牌級完整漏斗（進線 → 約成 → 到場 → 成案 → 轉出）
CREATE OR REPLACE VIEW v_consult_brand_funnel AS
SELECT
    b.brand_code,
    b.display_name                              AS brand_name,
    f.month_start,
    SUM(f.leads)                                AS total_leads,
    SUM(f.sessions)                             AS scheduled_sessions,
    o.consultations                             AS attended_sessions,
    o.signed_cases,
    o.transferred_to_010,
    -- 約成→到場
    CASE WHEN SUM(f.sessions) > 0
         THEN ROUND((o.consultations::NUMERIC / SUM(f.sessions)) * 100, 2)
         ELSE NULL END                          AS show_up_pct,
    -- 到場→成案
    CASE WHEN o.consultations > 0
         THEN ROUND((o.signed_cases::NUMERIC / o.consultations) * 100, 2)
         ELSE NULL END                          AS sign_pct,
    -- 進線→成案 (整體漏斗效率)
    CASE WHEN SUM(f.leads) > 0
         THEN ROUND((o.signed_cases::NUMERIC / SUM(f.leads)) * 100, 2)
         ELSE NULL END                          AS lead_to_sign_pct
FROM consult_brands b
LEFT JOIN consult_oa_master oa ON oa.brand_code = b.brand_code
LEFT JOIN consult_oa_monthly_funnel f ON f.oa_code = oa.oa_code
LEFT JOIN consult_brand_monthly_outcomes o
    ON o.brand_code = b.brand_code AND o.month_start = f.month_start
GROUP BY b.brand_code, b.display_name, f.month_start,
         o.consultations, o.signed_cases, o.transferred_to_010;


-- ────────────────────────────────────────────────────────────
--  5. 種子資料：4 個品牌 + 14 個 OA（13 active + FastLaw）
-- ────────────────────────────────────────────────────────────

INSERT INTO consult_brands (brand_code, display_name, category, notes) VALUES
    ('85010',   '85010',     '綜合',     '主力品牌之一'),
    ('JBK',     '金貝殼',    '債務催收', '債務催收垂直品牌'),
    ('GUITAR',  '吉他',      '綜合',     '律師談吉他主題'),
    ('FASTLAW', 'FastLaw',   '免費諮詢', '法速答品牌')
ON CONFLICT (brand_code) DO NOTHING;

INSERT INTO consult_oa_master (oa_code, brand_code, oa_display_name, is_main, slash_pattern, notes) VALUES
    -- 85010 系列
    ('FA',  '85010', '85010🐝您的專屬法律顧問',     TRUE,  '🐝',    '主號'),
    ('1FA', '85010', '85010/您的專屬法律顧問',      FALSE, '/',     'Clone 1（單斜線）'),
    ('2FA', '85010', '85010//您的專屬法律顧問',     FALSE, '//',    'Clone 2'),
    ('3FA', '85010', '85010///您的專屬法律顧問',    FALSE, '///',   'Clone 3'),
    ('4FA', '85010', '85010 \您的專屬法律顧問',     FALSE, '\',     'Clone 4（單反斜線）'),
    ('5FA', '85010', '85010 \\您的專屬法律顧問',    FALSE, '\\',    'Clone 5'),
    ('6FA', '85010', '85010 \\\您的專屬法律顧問',   FALSE, '\\\',   'Clone 6'),
    -- 金貝殼 系列
    ('MB',  'JBK',   '金貝殼🍯債務催收免費諮詢',    TRUE,  '🍯',    '主號'),
    ('1MB', 'JBK',   '金貝殼/債務催收免費諮詢',     FALSE, '/',     'Clone 1'),
    ('2MB', 'JBK',   '金貝殼//債務催收免費諮詢',    FALSE, '//',    'Clone 2'),
    ('3MB', 'JBK',   '金貝殼///債務催收免費諮詢',   FALSE, '///',   'Clone 3'),
    ('4MB', 'JBK',   '金貝殼////債務催收免費諮詢',  FALSE, '////',  'Clone 4'),
    -- 吉他 系列
    ('Z',   'GUITAR','喆律法律事務所/律師談吉他',   TRUE,  '/',     '主（859 友）'),
    ('1Z',  'GUITAR','喆律法律事務所/律師談吉他',   FALSE, '/',     '副（385 友）'),
    -- FastLaw
    ('FL',  'FASTLAW','FastLaw法速答 - 免費法律諮詢', TRUE, NULL,  '單一帳號')
ON CONFLICT (oa_code) DO NOTHING;


-- ────────────────────────────────────────────────────────────
--  6. RLS（與既有 advisor_* 模式一致）
-- ────────────────────────────────────────────────────────────

ALTER TABLE consult_brands                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_oa_master                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_staff                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_oa_monthly_funnel           ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_brand_monthly_outcomes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_staff_monthly_sessions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_consultations               ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_no_shows                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE consult_conversion_cycles           ENABLE ROW LEVEL SECURITY;

-- 所有已登入使用者可讀（BI 資料）
CREATE POLICY consult_brands_select         ON consult_brands         FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_oa_master_select      ON consult_oa_master      FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_staff_select          ON consult_staff          FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_oa_funnel_select      ON consult_oa_monthly_funnel       FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_brand_outcomes_select ON consult_brand_monthly_outcomes  FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_staff_sessions_select ON consult_staff_monthly_sessions  FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_consultations_select  ON consult_consultations  FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_no_shows_select       ON consult_no_shows       FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY consult_conversion_cycles_select ON consult_conversion_cycles FOR SELECT USING (auth.uid() IS NOT NULL);

-- 寫入由 admin / service role 控制（給 ETL 用）
CREATE POLICY consult_brands_admin         ON consult_brands         FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_oa_master_admin      ON consult_oa_master      FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_staff_admin          ON consult_staff          FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_oa_funnel_admin      ON consult_oa_monthly_funnel       FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_brand_outcomes_admin ON consult_brand_monthly_outcomes  FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_staff_sessions_admin ON consult_staff_monthly_sessions  FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_consultations_admin  ON consult_consultations  FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_no_shows_admin       ON consult_no_shows       FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY consult_conversion_cycles_admin ON consult_conversion_cycles FOR ALL USING (is_admin()) WITH CHECK (is_admin());
