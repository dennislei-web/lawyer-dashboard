-- ============================================================
--  法律顧問儀表板 - Schema
--  資料來源：Google Sheet 「法顧成案清單」
--    - Tab 1 (業績成案清單)        → advisor_cases
--    - Tab inbound 數據             → advisor_inbound_funnel
--    - Tab 電話陌開促成拜訪進度     → advisor_outbound_visits
--  同步機制：Apps Script 每日 02:00 推送到 Supabase（單向 Sheet → DB）
--  前置條件：lawyers 表已存在、is_admin() 函數已存在
-- ============================================================

-- 1. 案件清單（每筆已成案 / 候簽案）
CREATE TABLE IF NOT EXISTS advisor_cases (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 來源欄位（Sheet 原始）
    client_name                 TEXT,                  -- A 公司名/法顧當事人
    case_reason                 TEXT,                  -- B 案由、預設款日期
    source_category_raw         TEXT,                  -- C 案源類別 原始（人脈/新案/續委任）
    client_source_raw           TEXT,                  -- D 客戶來源 原始
    is_signed                   BOOLEAN DEFAULT false, -- E 已簽約
    amount_paid                 NUMERIC(12,0),         -- F 已付款金額
    paid_at                     DATE,                  -- G 付款日期
    salesperson                 TEXT,                  -- H 負責業務
    office                      TEXT,                  -- I 承辦所別
    first_contact_at            DATE,                  -- J 首次聯繫日期
    consultation_lawyer_closed  BOOLEAN,               -- K 有無諮詢律師成案
    handling_lawyers            TEXT[],                -- L 承辦律師（多人用 / 拆分）
    weight_flags                TEXT,                  -- AC-AE 加權旗標合併（v1 不參與計算）
    -- 衍生欄位（Apps Script 端計算後寫入）
    case_seq_for_client         INTEGER,               -- 同 client_name 第 N 筆（按 paid_at 排序）
    case_category               TEXT CHECK (case_category IN (
        '續委任','舊客衍生','諮詢轉案','人脈轉介','自行進線新案','未分類'
    )),
    -- 同步資訊
    sheet_row_index             INTEGER,               -- Sheet 中該筆的列號（debug 用）
    row_hash                    TEXT,                  -- 內容 hash 偵測修改
    synced_at                   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_advisor_cases_paid_at  ON advisor_cases(paid_at);
CREATE INDEX IF NOT EXISTS idx_advisor_cases_client   ON advisor_cases(client_name);
CREATE INDEX IF NOT EXISTS idx_advisor_cases_category ON advisor_cases(case_category);
CREATE INDEX IF NOT EXISTS idx_advisor_cases_office   ON advisor_cases(office);


-- 2. inbound 漏斗（每月一列）
CREATE TABLE IF NOT EXISTS advisor_inbound_funnel (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fiscal_year         INTEGER NOT NULL,
    month               INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    referral_faling     INTEGER DEFAULT 0,   -- 法零轉介
    referral_pre_retain INTEGER DEFAULT 0,   -- 委前轉介
    refused_line        INTEGER DEFAULT 0,   -- 不願意轉 line 頻道
    line_only           INTEGER DEFAULT 0,   -- 只願意 line 上溝通
    meeting_phone       INTEGER DEFAULT 0,   -- 克威電話會議
    meeting_video       INTEGER DEFAULT 0,   -- 克威視訊會議
    meeting_onsite      INTEGER DEFAULT 0,   -- 克威現場會議
    signed              INTEGER DEFAULT 0,   -- 促成簽約
    paid                INTEGER DEFAULT 0,   -- 促成付款
    notes_referral      TEXT,                -- 法零/委前 公司名清單原文
    notes_remark        TEXT,                -- 備註
    synced_at           TIMESTAMPTZ DEFAULT now(),
    UNIQUE(fiscal_year, month)
);

CREATE INDEX IF NOT EXISTS idx_advisor_funnel_ym ON advisor_inbound_funnel(fiscal_year, month);


-- 3. outbound 拜訪
CREATE TABLE IF NOT EXISTS advisor_outbound_visits (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq                 INTEGER,           -- A 編號
    brand               TEXT,              -- B 品牌
    account             TEXT,              -- C 帳號
    region              TEXT,              -- D 地區
    company_name        TEXT,              -- E 姓名/公司
    contact_phone       TEXT,              -- F 聯絡電話
    has_conflict_check  BOOLEAN,           -- G 建立利衝
    attended            BOOLEAN,           -- H 是否出席
    visited_at          DATE,              -- I 克威拜訪日期
    case_summary        TEXT,              -- J 案件簡述
    remark              TEXT,              -- K 備註
    is_retained         BOOLEAN,           -- L 是否委任
    advisor_window      TEXT,              -- M 法顧窗口
    sheet_row_index     INTEGER,
    row_hash            TEXT,
    synced_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_advisor_outbound_visited ON advisor_outbound_visits(visited_at);
CREATE INDEX IF NOT EXISTS idx_advisor_outbound_company ON advisor_outbound_visits(company_name);


-- 4. 同步紀錄
CREATE TABLE IF NOT EXISTS advisor_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheet_tab       TEXT NOT NULL,         -- '業績成案清單' / 'inbound數據' / '電話陌開促成拜訪進度'
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    rows_deleted    INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_advisor_sync_log_started ON advisor_sync_log(started_at DESC);


-- ============================================================
--  RLS：登入即可讀，僅 admin / service_role 可寫
-- ============================================================

ALTER TABLE advisor_cases            ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_inbound_funnel   ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_outbound_visits  ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_sync_log         ENABLE ROW LEVEL SECURITY;

-- SELECT: 所有登入使用者可讀
CREATE POLICY advisor_cases_select          ON advisor_cases
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_funnel_select         ON advisor_inbound_funnel
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_outbound_select       ON advisor_outbound_visits
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_sync_log_select       ON advisor_sync_log
    FOR SELECT USING (auth.uid() IS NOT NULL);

-- INSERT/UPDATE/DELETE: 僅 admin（Apps Script 用 service_role key 自動繞過 RLS）
CREATE POLICY advisor_cases_admin           ON advisor_cases
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY advisor_funnel_admin          ON advisor_inbound_funnel
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY advisor_outbound_admin        ON advisor_outbound_visits
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
CREATE POLICY advisor_sync_log_admin        ON advisor_sync_log
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
