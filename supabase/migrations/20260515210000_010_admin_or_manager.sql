-- 法律010 RLS：admin 全部 + manager 含 dashboard_access='law010' 才能看
-- 對應其他 dashboard 的權限粒度

CREATE OR REPLACE FUNCTION has_law010_access()
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM lawyers
    WHERE auth_user_id = auth.uid()
      AND is_active = true
      AND (
        role = 'admin'
        OR (role = 'manager' AND 'law010' = ANY(dashboard_access))
      )
  );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

DROP POLICY IF EXISTS raw_010_case_select ON raw_010_case;
CREATE POLICY raw_010_case_select ON raw_010_case FOR SELECT
  TO authenticated USING (has_law010_access());

DROP POLICY IF EXISTS raw_010_installment_select ON raw_010_installment_case;
CREATE POLICY raw_010_installment_select ON raw_010_installment_case FOR SELECT
  TO authenticated USING (has_law010_access());

DROP POLICY IF EXISTS raw_010_target_select ON raw_010_lawyer_target;
CREATE POLICY raw_010_target_select ON raw_010_lawyer_target FOR SELECT
  TO authenticated USING (has_law010_access());

DROP POLICY IF EXISTS fact_team_select ON fact_010_monthly_team;
CREATE POLICY fact_team_select ON fact_010_monthly_team FOR SELECT
  TO authenticated USING (has_law010_access());

DROP POLICY IF EXISTS fact_lawyer_select ON fact_010_monthly_lawyer;
CREATE POLICY fact_lawyer_select ON fact_010_monthly_lawyer FOR SELECT
  TO authenticated USING (has_law010_access());
