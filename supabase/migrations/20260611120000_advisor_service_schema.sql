-- ============================================================
--  法律顧問儀表板 - 委後服務模組（Phase 1）
--  依《法顧部門服務SOP》設計：簽約後的開案交接、委後服務、合約週期管理
--  與 Sheet 同步表（advisor_cases / advisor_pending_cases）分離：
--    本組表為儀表板原生 SoT，可直接在 UI 編輯，不受每日清表重灌影響
--  設計文件：法顧委後服務模組設計.md
-- ============================================================

-- 0. 角色判斷（security definer 防 RLS 遞迴；manager 與 admin 視為主管）
CREATE OR REPLACE FUNCTION is_manager()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM lawyers
        WHERE auth_user_id = auth.uid() AND role IN ('manager', 'admin')
    );
$$;

-- 1. 委後服務案件
--    stage 接續 advisor_pending_cases.current_stage（…→ 已成案）之後的生命週期
CREATE TABLE IF NOT EXISTS advisor_service_cases (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    advisor_case_id   UUID REFERENCES advisor_cases(id) ON DELETE SET NULL,  -- 軟連結成案紀錄（Sheet 同步表，可空）
    pending_case_id   UUID,                            -- 來源跟進中案件 id（不設 FK：該表會清表重灌）
    client_name       TEXT NOT NULL,
    client_vat        TEXT,                            -- 統編（歸戶 key，同名戶區分用）
    client_phone      TEXT,
    opposing_party    TEXT,                            -- 對造名稱（SOP：每份新合約須鍵入防利衝）
    case_type         TEXT,                            -- 委任項目/案由（法律顧問、合約審閱…）
    source            TEXT,                            -- 來源（沿用 case_category 分類或自由文字）
    stage             TEXT NOT NULL DEFAULT '已簽約' CHECK (stage IN (
        '已簽約','收款確認','交接中','已分案','服務中','續約評估','已續約','已流失'
    )),
    designated_lawyer TEXT,                            -- 指定律師（SOP：契約需註記、委後以其名義打招呼）
    handling_lawyer   TEXT,                            -- 承辦律師
    salesperson       TEXT,                            -- 負責業務顯示名（克威/柏凱/偉志…）
    owner_id          UUID REFERENCES lawyers(id) ON DELETE SET NULL,  -- 負責業務帳號連結（有 Auth 帳號才綁）
    office            TEXT,
    line_channel      TEXT,                            -- 委後 LINE@ 連結
    fee_amount        NUMERIC(12,0),                   -- 委任費（NT$）
    contract_start    DATE,
    contract_end      DATE,
    purchased_hours   NUMERIC(8,1),                    -- 已購時數/點數
    monthly_report    BOOLEAN NOT NULL DEFAULT false,  -- 黏著度標籤：每月報告
    switch_lawyer     BOOLEAN NOT NULL DEFAULT false,  -- 黏著度標籤：換律師
    handover          JSONB NOT NULL DEFAULT '{}',     -- 開案交接 checklist（key: boolean/text，前端定義項目）
    note              TEXT,
    external_ref      TEXT,                            -- 預留外部系統案件編號
    created_by        UUID REFERENCES lawyers(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_service_cases_stage        ON advisor_service_cases(stage);
CREATE INDEX IF NOT EXISTS idx_service_cases_client       ON advisor_service_cases(client_name);
CREATE INDEX IF NOT EXISTS idx_service_cases_contract_end ON advisor_service_cases(contract_end);
CREATE INDEX IF NOT EXISTS idx_service_cases_salesperson  ON advisor_service_cases(salesperson);

CREATE TRIGGER advisor_service_cases_updated_at
    BEFORE UPDATE ON advisor_service_cases
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 2. 跟追歷程（SOP：通話/會議後須留痕「承剛剛電話討論…」）
CREATE TABLE IF NOT EXISTS advisor_case_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id     UUID NOT NULL REFERENCES advisor_service_cases(id) ON DELETE CASCADE,
    author_id   UUID REFERENCES lawyers(id) ON DELETE SET NULL,
    author_name TEXT,                                  -- 顯示名快照（帳號刪除後仍可讀）
    event_type  TEXT NOT NULL DEFAULT 'note' CHECK (event_type IN (
        'note','call','meeting','hours','renewal','stage_change'
    )),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_case_events_case ON advisor_case_events(case_id, created_at DESC);

-- 3. 時數帳（Phase 1 先建表 + 手動輸入；Phase 2 接 CRM 爬蟲）
CREATE TABLE IF NOT EXISTS advisor_hour_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id     UUID NOT NULL REFERENCES advisor_service_cases(id) ON DELETE CASCADE,
    work_date   DATE NOT NULL,
    hours       NUMERIC(5,1) NOT NULL,
    entry_kind  TEXT NOT NULL DEFAULT 'work' CHECK (entry_kind IN ('work','quote')),  -- SOP 區分工作/報價時數
    description TEXT,                                  -- 工作事項（SOP：要寫得讓客戶覺得有價值）
    lawyer_name TEXT,
    created_by  UUID REFERENCES lawyers(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hour_entries_case ON advisor_hour_entries(case_id, work_date DESC);

-- ============================================================
--  RLS：登入可讀（跨業務透明，主管會議需全貌）
--  寫入：負責業務本人（owner_id 連 Auth）或 manager/admin
--  刪除：僅 manager/admin
--  註：克威/柏凱目前無 Auth 帳號，實務上由偉志(manager)/admin 操作；
--      日後開帳號後把 lawyers.auth_user_id 補上、案件綁 owner_id 即可
-- ============================================================

ALTER TABLE advisor_service_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_case_events   ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_hour_entries  ENABLE ROW LEVEL SECURITY;

-- 共用條件：owner 本人
CREATE OR REPLACE FUNCTION is_service_case_owner(p_case_id UUID)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
    SELECT EXISTS (
        SELECT 1 FROM advisor_service_cases c
        JOIN lawyers l ON l.id = c.owner_id
        WHERE c.id = p_case_id AND l.auth_user_id = auth.uid()
    );
$$;

-- advisor_service_cases
CREATE POLICY service_cases_select ON advisor_service_cases
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY service_cases_insert ON advisor_service_cases
    FOR INSERT WITH CHECK (
        is_manager() OR EXISTS (
            SELECT 1 FROM lawyers l WHERE l.id = owner_id AND l.auth_user_id = auth.uid()
        )
    );
CREATE POLICY service_cases_update ON advisor_service_cases
    FOR UPDATE USING (is_manager() OR is_service_case_owner(id))
    WITH CHECK (is_manager() OR is_service_case_owner(id));
CREATE POLICY service_cases_delete ON advisor_service_cases
    FOR DELETE USING (is_manager());

-- advisor_case_events（權限依所屬案件；歷程不可改、僅 manager 可刪）
CREATE POLICY case_events_select ON advisor_case_events
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY case_events_insert ON advisor_case_events
    FOR INSERT WITH CHECK (is_manager() OR is_service_case_owner(case_id));
CREATE POLICY case_events_delete ON advisor_case_events
    FOR DELETE USING (is_manager());

-- advisor_hour_entries
CREATE POLICY hour_entries_select ON advisor_hour_entries
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY hour_entries_insert ON advisor_hour_entries
    FOR INSERT WITH CHECK (is_manager() OR is_service_case_owner(case_id));
CREATE POLICY hour_entries_update ON advisor_hour_entries
    FOR UPDATE USING (is_manager() OR is_service_case_owner(case_id))
    WITH CHECK (is_manager() OR is_service_case_owner(case_id));
CREATE POLICY hour_entries_delete ON advisor_hour_entries
    FOR DELETE USING (is_manager());
