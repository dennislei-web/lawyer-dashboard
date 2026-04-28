-- ============================================================
--  法律顧問儀表板 - 跟進中案件 (克威柏凱輪值表)
--  資料來源：Google Sheet 「法顧成案清單」 → 「2. 克威柏凱輪值表」分頁
--  每一列代表一個尚未成案、業務正在跟進的案件
-- ============================================================

CREATE TABLE IF NOT EXISTS advisor_pending_cases (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 來源欄位
    monthly_seq              INTEGER,        -- A 當月編號
    salesperson              TEXT,           -- B 負責同仁（克威/柏凱/偉志）
    assigned_at              DATE,           -- C 交辦日期
    client_name              TEXT,           -- D 當事人
    is_paid                  BOOLEAN,        -- E 已付款（部分情況代表已成案）
    channel                  TEXT,           -- F 管道來源
    consultation_lawyer      TEXT,           -- G 律師諮詢
    last_contact_text        TEXT,           -- H 最近一次聯繫時間（自由文字）
    case_summary             TEXT,           -- I 簡述案件
    first_contact_at         DATE,           -- J 初次接觸日期
    cm_meeting_at            DATE,           -- K 客戶經理會議日期
    lawyer_meeting_at        DATE,           -- L 律師會議日期（無則 2000/01/01）
    proposal_at              DATE,           -- M 提報方案日期
    follow_up_1_at           DATE,           -- N 提報追蹤日期
    follow_up_2_at           DATE,           -- O 第二次追蹤日期
    lawyer_notes             TEXT,           -- P 律師協助 / 特殊情形
    is_signed                BOOLEAN,        -- Q 簽約
    payment_status           TEXT,           -- R 付款（自由文字）
    -- 衍生欄位（Apps Script 端推導）
    current_stage            TEXT CHECK (current_stage IN (
        '尚未啟動','初次接觸','客戶經理會議','律師會議','提報方案','提報追蹤','第二次追蹤','已成案'
    )),
    days_since_assigned      INTEGER,        -- 交辦至同步當下的天數
    days_since_last_action   INTEGER,        -- 距最後一個有日期的階段的天數
    -- 同步資訊
    sheet_row_index          INTEGER,
    row_hash                 TEXT,
    synced_at                TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pending_assigned    ON advisor_pending_cases(assigned_at);
CREATE INDEX IF NOT EXISTS idx_pending_salesperson ON advisor_pending_cases(salesperson);
CREATE INDEX IF NOT EXISTS idx_pending_stage       ON advisor_pending_cases(current_stage);
CREATE INDEX IF NOT EXISTS idx_pending_client      ON advisor_pending_cases(client_name);

ALTER TABLE advisor_pending_cases ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_pending_select ON advisor_pending_cases
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_pending_admin ON advisor_pending_cases
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());
