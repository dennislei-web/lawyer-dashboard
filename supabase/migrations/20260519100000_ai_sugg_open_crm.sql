-- 開放 consultation_ai_suggestions 給客戶關係部（CRM@zhelu.tw）
-- 背景：接案法務統一用 CRM@zhelu.tw 帳號看追單建議；不能只給 dennis。

DROP POLICY IF EXISTS ai_sugg_dennis_only ON consultation_ai_suggestions;
DROP POLICY IF EXISTS ai_sugg_dennis_or_crm ON consultation_ai_suggestions;

CREATE POLICY ai_sugg_dennis_or_crm ON consultation_ai_suggestions
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lower(lawyers.email) IN ('dennis.lei@010.tw', 'crm@zhelu.tw')
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lower(lawyers.email) IN ('dennis.lei@010.tw', 'crm@zhelu.tw')
    )
  );

COMMENT ON POLICY ai_sugg_dennis_or_crm ON consultation_ai_suggestions IS
  'dennis（觀察 AI 品質）+ 客戶關係部 CRM@zhelu.tw（接案法務統一帳號）兩者可讀寫';
