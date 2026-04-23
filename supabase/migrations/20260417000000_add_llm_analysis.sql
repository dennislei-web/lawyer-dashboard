-- =====================================================
-- Migration: 新增 LLM 歸因分析欄位
-- 用途：儲存 Claude 對每筆 consultation_case 的結構化分析結果
-- =====================================================

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS llm_analysis JSONB,
  ADD COLUMN IF NOT EXISTS llm_analyzed_at TIMESTAMPTZ;

-- GIN 索引方便未來查詢（例如找 failure_reason = '價格疑慮' 的案件）
CREATE INDEX IF NOT EXISTS idx_cases_llm_analysis
  ON public.consultation_cases USING gin(llm_analysis);

-- 註釋
COMMENT ON COLUMN public.consultation_cases.llm_analysis IS
  'LLM 歸因分析結構化輸出：{failure_reason, reason_evidence, missed_opportunities[], strengths[], improvement_for_lawyer, transferable_pattern, model, prompt_version}';
COMMENT ON COLUMN public.consultation_cases.llm_analyzed_at IS
  'LLM 分析執行時間，用於追蹤是否需要重跑';
