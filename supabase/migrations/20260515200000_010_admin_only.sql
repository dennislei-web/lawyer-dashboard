-- 法律010 dashboard 收緊權限 → 只 admin 可看
-- 原本 RLS 設 TO authenticated USING (true)，44 位 active lawyer 全部能看
-- 改成只 admin (3 人)：雷皓明 / 張飛宇 / 股東

DROP POLICY IF EXISTS raw_010_case_select ON raw_010_case;
CREATE POLICY raw_010_case_select ON raw_010_case FOR SELECT
  TO authenticated USING (is_admin());

DROP POLICY IF EXISTS raw_010_installment_select ON raw_010_installment_case;
CREATE POLICY raw_010_installment_select ON raw_010_installment_case FOR SELECT
  TO authenticated USING (is_admin());

DROP POLICY IF EXISTS raw_010_target_select ON raw_010_lawyer_target;
CREATE POLICY raw_010_target_select ON raw_010_lawyer_target FOR SELECT
  TO authenticated USING (is_admin());

DROP POLICY IF EXISTS fact_team_select ON fact_010_monthly_team;
CREATE POLICY fact_team_select ON fact_010_monthly_team FOR SELECT
  TO authenticated USING (is_admin());

DROP POLICY IF EXISTS fact_lawyer_select ON fact_010_monthly_lawyer;
CREATE POLICY fact_lawyer_select ON fact_010_monthly_lawyer FOR SELECT
  TO authenticated USING (is_admin());
