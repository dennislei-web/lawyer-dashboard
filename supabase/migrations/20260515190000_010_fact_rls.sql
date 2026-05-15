-- 法律010 fact / raw 表 RLS
-- 允許 admin + 「dashboard_access 勾選 010」用戶讀取
-- 注意：sync_010.py 用 service_role 寫入，bypass RLS

-- 假設 lawyers.dashboard_access 已有「010」欄位（jsonb 或 text array），
-- 若沒先給 admin 跟 「can_view_all」 access; 之後可加更精細 policy

ALTER TABLE raw_010_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_010_installment_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_010_lawyer_target ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_010_monthly_team ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_010_monthly_lawyer ENABLE ROW LEVEL SECURITY;

-- 為簡化 v1：所有 authenticated 用戶都可讀 (跟 partner_cross_referral 等 dashboard 同層級)
-- 後續可加細緻 policy

DROP POLICY IF EXISTS raw_010_case_select ON raw_010_case;
CREATE POLICY raw_010_case_select ON raw_010_case FOR SELECT
  TO authenticated USING (true);

DROP POLICY IF EXISTS raw_010_installment_select ON raw_010_installment_case;
CREATE POLICY raw_010_installment_select ON raw_010_installment_case FOR SELECT
  TO authenticated USING (true);

DROP POLICY IF EXISTS raw_010_target_select ON raw_010_lawyer_target;
CREATE POLICY raw_010_target_select ON raw_010_lawyer_target FOR SELECT
  TO authenticated USING (true);

DROP POLICY IF EXISTS fact_team_select ON fact_010_monthly_team;
CREATE POLICY fact_team_select ON fact_010_monthly_team FOR SELECT
  TO authenticated USING (true);

DROP POLICY IF EXISTS fact_lawyer_select ON fact_010_monthly_lawyer;
CREATE POLICY fact_lawyer_select ON fact_010_monthly_lawyer FOR SELECT
  TO authenticated USING (true);
