-- ============================================================
--  Migration: 更新 revenue_records 以匹配 CRM 對帳頁面實際欄位
-- ============================================================

-- 1. 先清除範例資料
DELETE FROM monthly_revenue_stats;
DELETE FROM revenue_records;
DELETE FROM department_members;
DELETE FROM departments;

-- 2. 新增 revenue_records 欄位
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS transaction_id TEXT UNIQUE;
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS transaction_type TEXT;  -- PaymentTransaction / RefundTransaction
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS payment_method TEXT;
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS is_void BOOLEAN DEFAULT false;
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS brand TEXT;            -- 85010 / zhelu / moneyback
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS office TEXT;           -- 接案所: 台中所/台北所/...
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS group_name TEXT;       -- 部門: 北所一部/中所合署(...)
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS service_items TEXT;    -- 服務項目
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS accrued_expense NUMERIC DEFAULT 0;  -- 應收總額
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS assigned_lawyers TEXT; -- 接案人員
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS responsible_lawyer TEXT; -- 負責人員

-- 3. 移除不需要的欄位 (case_number 保留但改用 transaction_id，case_type 改用 service_items)
-- 保留相容性，不刪除舊欄位

-- 4. 更新 departments 表，改為接案所
INSERT INTO departments (name) VALUES
  ('台中所'), ('台北所'), ('台南所'), ('新竹所'), ('桃園所'), ('高雄所')
ON CONFLICT (name) DO NOTHING;

-- 5. 更新 index
CREATE INDEX IF NOT EXISTS idx_revenue_office ON revenue_records(office);
CREATE INDEX IF NOT EXISTS idx_revenue_group ON revenue_records(group_name);
CREATE INDEX IF NOT EXISTS idx_revenue_brand ON revenue_records(brand);
CREATE INDEX IF NOT EXISTS idx_revenue_txn_type ON revenue_records(transaction_type);
CREATE INDEX IF NOT EXISTS idx_revenue_txn_id ON revenue_records(transaction_id);

-- 6. 更新 Views
DROP VIEW IF EXISTS department_revenue_summary;
CREATE OR REPLACE VIEW department_revenue_summary AS
SELECT
    r.office AS office_name,
    r.group_name,
    COUNT(r.id) AS total_transactions,
    COUNT(r.id) FILTER (WHERE r.transaction_type = 'PaymentTransaction') AS payment_count,
    COUNT(r.id) FILTER (WHERE r.transaction_type = 'RefundTransaction') AS refund_count,
    COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'PaymentTransaction' AND NOT r.is_void), 0) AS total_payments,
    COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'RefundTransaction' AND NOT r.is_void), 0) AS total_refunds,
    COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'PaymentTransaction' AND NOT r.is_void), 0)
    - COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'RefundTransaction' AND NOT r.is_void), 0) AS net_revenue
FROM revenue_records r
WHERE NOT r.is_void
GROUP BY r.office, r.group_name;

DROP VIEW IF EXISTS source_channel_stats;
CREATE OR REPLACE VIEW source_channel_stats AS
SELECT
    r.source_channel,
    COUNT(r.id) AS transaction_count,
    COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'PaymentTransaction' AND NOT r.is_void), 0) AS total_payments,
    COALESCE(SUM(r.amount) FILTER (WHERE r.transaction_type = 'RefundTransaction' AND NOT r.is_void), 0) AS total_refunds
FROM revenue_records r
WHERE r.source_channel IS NOT NULL AND NOT r.is_void
GROUP BY r.source_channel;

-- 7. revenue_records 改用 amount 欄位（合併 revenue/collected/refund）
-- amount 就是交易金額，transaction_type 區分付款/退款
-- 保留 revenue/collected/refund 欄位相容性，但新資料改用 amount
ALTER TABLE revenue_records ADD COLUMN IF NOT EXISTS amount NUMERIC DEFAULT 0;
