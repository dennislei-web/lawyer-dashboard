-- ============================================================
--  營運儀表板 - 新增資料表（在現有 Supabase 專案中執行）
--  注意：lawyers 表已存在，此處僅新增營運相關表
-- ============================================================

-- 1. 部門
CREATE TABLE IF NOT EXISTS departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 2. 部門成員（連結 lawyers 表）
CREATE TABLE IF NOT EXISTS department_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id   UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    lawyer_id       UUID NOT NULL REFERENCES lawyers(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'manager')),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(department_id, lawyer_id)
);

CREATE INDEX IF NOT EXISTS idx_dept_members_dept ON department_members(department_id);
CREATE INDEX IF NOT EXISTS idx_dept_members_lawyer ON department_members(lawyer_id);

-- 3. 營收記錄（逐筆）
CREATE TABLE IF NOT EXISTS revenue_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_date     DATE NOT NULL,
    department_id   UUID REFERENCES departments(id),
    lawyer_id       UUID REFERENCES lawyers(id),
    case_number     TEXT,
    client_name     TEXT,
    case_type       TEXT,
    source_channel  TEXT,         -- 來源管道: 網路/推薦/廣告/法扶/自來客/...
    revenue         NUMERIC DEFAULT 0,  -- 應收金額
    collected       NUMERIC DEFAULT 0,  -- 已收金額
    refund          NUMERIC DEFAULT 0,  -- 退款金額
    status          TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_revenue_date ON revenue_records(record_date);
CREATE INDEX IF NOT EXISTS idx_revenue_dept ON revenue_records(department_id);
CREATE INDEX IF NOT EXISTS idx_revenue_lawyer ON revenue_records(lawyer_id);

-- 4. 月度營收統計（按部門彙總）
CREATE TABLE IF NOT EXISTS monthly_revenue_stats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    month           TEXT NOT NULL,  -- format: '2026-03'
    department_id   UUID REFERENCES departments(id),
    total_revenue   NUMERIC DEFAULT 0,
    total_collected NUMERIC DEFAULT 0,
    total_refund    NUMERIC DEFAULT 0,
    case_count      INTEGER DEFAULT 0,
    new_case_count  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(month, department_id)
);

-- updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS monthly_revenue_stats_updated_at ON monthly_revenue_stats;
CREATE TRIGGER monthly_revenue_stats_updated_at
    BEFORE UPDATE ON monthly_revenue_stats
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
--  Views
-- ============================================================

-- 部門彙總 view
CREATE OR REPLACE VIEW department_revenue_summary AS
SELECT
    d.id AS department_id,
    d.name AS department_name,
    COUNT(r.id) AS total_cases,
    COALESCE(SUM(r.revenue), 0) AS total_revenue,
    COALESCE(SUM(r.collected), 0) AS total_collected,
    COALESCE(SUM(r.refund), 0) AS total_refund,
    COALESCE(SUM(r.revenue), 0) - COALESCE(SUM(r.refund), 0) AS net_revenue
FROM departments d
LEFT JOIN revenue_records r ON r.department_id = d.id
GROUP BY d.id, d.name;

-- 來源管道統計 view
CREATE OR REPLACE VIEW source_channel_stats AS
SELECT
    source_channel,
    COUNT(*) AS case_count,
    COALESCE(SUM(revenue), 0) AS total_revenue,
    COALESCE(SUM(collected), 0) AS total_collected,
    COALESCE(SUM(refund), 0) AS total_refund
FROM revenue_records
WHERE source_channel IS NOT NULL
GROUP BY source_channel;

-- ============================================================
--  RLS（部門主管制）
-- ============================================================

ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE department_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_revenue_stats ENABLE ROW LEVEL SECURITY;

-- Helper function: 取得使用者的 lawyer_id
CREATE OR REPLACE FUNCTION get_my_lawyer_id()
RETURNS UUID AS $$
    SELECT id FROM lawyers WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- Helper function: 檢查是否為 admin
CREATE OR REPLACE FUNCTION is_admin()
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM lawyers
        WHERE auth_user_id = auth.uid() AND role = 'admin'
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- Helper function: 取得使用者所屬部門 IDs
CREATE OR REPLACE FUNCTION get_my_department_ids()
RETURNS SETOF UUID AS $$
    SELECT department_id FROM department_members
    WHERE lawyer_id = get_my_lawyer_id();
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- departments: 所有登入使用者可讀
CREATE POLICY departments_select ON departments
    FOR SELECT USING (auth.uid() IS NOT NULL);

-- department_members: 看自己部門的成員，或 admin 看全部
CREATE POLICY dept_members_select ON department_members
    FOR SELECT USING (
        is_admin() OR department_id IN (SELECT get_my_department_ids())
    );

-- revenue_records: 部門成員看部門資料，admin 看全部
CREATE POLICY revenue_select ON revenue_records
    FOR SELECT USING (
        is_admin() OR department_id IN (SELECT get_my_department_ids())
    );

-- monthly_revenue_stats: 同上
CREATE POLICY monthly_revenue_select ON monthly_revenue_stats
    FOR SELECT USING (
        is_admin() OR department_id IN (SELECT get_my_department_ids())
    );

-- 寫入：僅 service_role（Python 腳本）可寫
-- （service_role 自動繞過 RLS，不需額外 policy）
