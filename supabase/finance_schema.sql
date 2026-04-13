-- ============================================================
--  財務規劃儀表板 - Schema
--  在現有 Supabase 專案中執行
--  前置條件：lawyers 表已存在、is_admin() 函數已存在
-- ============================================================

-- 1. 科目表
CREATE TABLE IF NOT EXISTS finance_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    section     TEXT NOT NULL CHECK (section IN ('revenue', 'operating_expense', 'non_operating_income', 'tax')),
    sort_order  INTEGER NOT NULL,
    is_subtotal BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 2. 財務資料（歷史/預算/實際）
CREATE TABLE IF NOT EXISTS finance_data (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id   UUID NOT NULL REFERENCES finance_categories(id),
    fiscal_year   INTEGER NOT NULL,
    month         INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    data_type     TEXT NOT NULL CHECK (data_type IN ('historical', 'budget', 'actual')),
    amount        NUMERIC(14,0) DEFAULT 0,
    notes         TEXT,
    updated_by    UUID REFERENCES lawyers(id),
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(category_id, fiscal_year, month, data_type)
);

CREATE INDEX IF NOT EXISTS idx_finance_data_year ON finance_data(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_finance_data_type ON finance_data(data_type);
CREATE INDEX IF NOT EXISTS idx_finance_data_cat  ON finance_data(category_id);

-- updated_at trigger
DROP TRIGGER IF EXISTS finance_data_updated_at ON finance_data;
CREATE TRIGGER finance_data_updated_at
    BEFORE UPDATE ON finance_data
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 3. 上傳紀錄
CREATE TABLE IF NOT EXISTS finance_uploads (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename      TEXT NOT NULL,
    fiscal_year   INTEGER NOT NULL,
    entity        TEXT NOT NULL,
    uploaded_by   UUID REFERENCES lawyers(id),
    row_count     INTEGER,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- 4. 員工薪資名冊
CREATE TABLE IF NOT EXISTS finance_employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    department      TEXT,
    base_salary     NUMERIC(10,0) DEFAULT 0,
    total_salary    NUMERIC(10,0) DEFAULT 0,
    total_pay       NUMERIC(10,0) DEFAULT 0,
    employer_labor  NUMERIC(10,0) DEFAULT 0,
    employer_health NUMERIC(10,0) DEFAULT 0,
    employer_pension NUMERIC(10,0) DEFAULT 0,
    employer_total  NUMERIC(10,0) DEFAULT 0,
    bonus           NUMERIC(10,0) DEFAULT 0,
    fiscal_year     INTEGER NOT NULL,
    is_active       BOOLEAN DEFAULT true,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_finance_emp_year ON finance_employees(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_finance_emp_name ON finance_employees(name);

-- 5. 預算調整紀錄
CREATE TABLE IF NOT EXISTS finance_adjustments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fiscal_year   INTEGER NOT NULL,
    category_id   UUID NOT NULL REFERENCES finance_categories(id),
    description   TEXT NOT NULL,
    amount        NUMERIC(14,0) NOT NULL,
    adjust_type   TEXT NOT NULL CHECK (adjust_type IN ('monthly', 'one_time')),
    start_month   INTEGER NOT NULL CHECK (start_month BETWEEN 1 AND 12),
    end_month     INTEGER NOT NULL CHECK (end_month BETWEEN 1 AND 12),
    is_active     BOOLEAN DEFAULT true,
    created_by    UUID REFERENCES lawyers(id),
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_finance_adj_year ON finance_adjustments(fiscal_year);

-- ============================================================
--  RLS
-- ============================================================

ALTER TABLE finance_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance_adjustments ENABLE ROW LEVEL SECURITY;

-- SELECT: 所有登入使用者可讀
CREATE POLICY finance_categories_select ON finance_categories
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY finance_data_select ON finance_data
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY finance_uploads_select ON finance_uploads
    FOR SELECT USING (auth.uid() IS NOT NULL);

-- INSERT/UPDATE/DELETE: 僅 admin
CREATE POLICY finance_categories_admin ON finance_categories
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY finance_data_admin ON finance_data
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY finance_uploads_admin ON finance_uploads
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

-- finance_employees
CREATE POLICY finance_employees_select ON finance_employees
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY finance_employees_admin ON finance_employees
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

-- finance_adjustments
CREATE POLICY finance_adjustments_select ON finance_adjustments
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY finance_adjustments_admin ON finance_adjustments
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

-- ============================================================
--  Seed 科目資料
-- ============================================================

INSERT INTO finance_categories (code, name, section, sort_order, is_subtotal) VALUES
  -- 營業收入
  ('revenue_gross',    '銷貨收入',       'revenue', 1, false),
  ('revenue_returns',  '減：銷貨退回',   'revenue', 2, false),
  ('revenue_net',      '營業收入淨額',   'revenue', 3, true),
  -- 營業費用
  ('salary',           '薪資費用',       'operating_expense', 10, false),
  ('rent',             '租金費用',       'operating_expense', 11, false),
  ('stationery',       '文具用品',       'operating_expense', 12, false),
  ('travel',           '旅費',           'operating_expense', 13, false),
  ('shipping',         '運費',           'operating_expense', 14, false),
  ('postage',          '郵電費',         'operating_expense', 15, false),
  ('repair',           '修繕費',         'operating_expense', 16, false),
  ('advertising',      '廣告費',         'operating_expense', 17, false),
  ('utilities',        '水電費',         'operating_expense', 18, false),
  ('insurance',        '保險費',         'operating_expense', 19, false),
  ('entertainment',    '交際費',         'operating_expense', 20, false),
  ('tax_expense',      '稅捐',           'operating_expense', 21, false),
  ('depreciation',     '折舊及耗竭',     'operating_expense', 22, false),
  ('amortization',     '各項攤銷',       'operating_expense', 23, false),
  ('welfare',          '職工福利',       'operating_expense', 24, false),
  ('training',         '教育訓練費用',   'operating_expense', 25, false),
  ('service_fee',      '勞務費用',       'operating_expense', 26, false),
  ('transport',        '交通燃料費',     'operating_expense', 27, false),
  ('printing',         '印刷影印費',     'operating_expense', 28, false),
  ('publications',     '書報雜誌',       'operating_expense', 29, false),
  ('misc_purchase',    '雜項購置',       'operating_expense', 30, false),
  ('sundry',           '什費',           'operating_expense', 31, false),
  ('pension',          '退休金',         'operating_expense', 32, false),
  ('bar_fee',          '律師公會費',     'operating_expense', 33, false),
  ('bonus_accrual',    '薪資支出(年終預估)', 'operating_expense', 34, false),
  ('bank_fee',         '手續費',         'operating_expense', 35, false),
  -- 營業外收入
  ('lease_income',     '租賃收益',       'non_operating_income', 50, false),
  ('other_income',     '其他收入',       'non_operating_income', 51, false),
  ('partner_income',   '合署律師合作收入', 'non_operating_income', 52, false),
  ('interest_income',  '利息收益',       'non_operating_income', 53, false),
  ('gov_subsidy',      '政府補助收益',   'non_operating_income', 54, false),
  -- 稅
  ('income_tax',       '所得稅',         'tax', 90, false)
ON CONFLICT (code) DO NOTHING;
