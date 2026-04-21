-- =====================================================
-- Migration: 新增 doc_uploaded_at 欄位
-- 用途：記錄會議記錄 / 逐字稿的上傳時間，讓儀表板能顯示
--       「最近什麼時候上傳」，協助同仁確認已傳 vs 未傳
-- =====================================================

ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS doc_uploaded_at TIMESTAMPTZ;

-- Backfill：既有已上傳的案件（meeting_record 或 transcript 非空）
-- 沒有原始上傳時戳，用最接近的 proxy：
--   llm_analyzed_at（LLM 通常在上傳後跑）> created_at（案件建立時間）
UPDATE public.consultation_cases
SET doc_uploaded_at = COALESCE(llm_analyzed_at, created_at)
WHERE doc_uploaded_at IS NULL
  AND (
    (meeting_record IS NOT NULL AND meeting_record <> '')
    OR (transcript IS NOT NULL AND transcript <> '')
  );

COMMENT ON COLUMN public.consultation_cases.doc_uploaded_at IS
  '會議記錄 / 逐字稿最近一次上傳時間（由 UI 上傳流程寫入）';
