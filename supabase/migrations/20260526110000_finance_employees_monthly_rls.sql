-- finance_employees_monthly 沒有任何 RLS policy → 連登入使用者都讀不到
-- 補上跟 finance_employees 一樣的政策

CREATE POLICY finance_employees_monthly_select ON finance_employees_monthly
  FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY finance_employees_monthly_admin ON finance_employees_monthly
  FOR ALL
  USING (is_admin());
