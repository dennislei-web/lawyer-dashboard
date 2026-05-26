-- Add office column to finance_employees_monthly
-- 對應 crm_cases.office_name (台北所/台中所/台南所/新竹所/桃園所/高雄所)
-- 用於案件狀態頁計算「人均承辦中案件」
-- 非接案所部門（公司/客服/法顧/法律010/品牌部/其他）設 NULL

ALTER TABLE finance_employees_monthly
  ADD COLUMN IF NOT EXISTS office text;

COMMENT ON COLUMN finance_employees_monthly.office IS
  '正規化接案所，對齊 crm_cases.office_name。非接案所部門為 NULL。';

CREATE INDEX IF NOT EXISTS idx_finance_employees_monthly_office_ym
  ON finance_employees_monthly (fiscal_year, month, office)
  WHERE office IS NOT NULL;
