-- AI 問答 RAG 檢索分流：
--   成案案件 → 只回傳真實對話（meeting_record / transcript），律師看真正成功的話術
--   未成案案件 → 保留全部 chunk 類型（含 llm_pattern / llm_missed_opp 等濃縮教訓）
-- 沿用 20260426000000_qa_match_chunks_is_signed.sql 的 schema，僅新增 WHERE 條件。

DROP FUNCTION IF EXISTS public.match_case_chunks(vector, int);

CREATE OR REPLACE FUNCTION public.match_case_chunks(
  query_embedding vector(1024),
  match_count int DEFAULT 8
)
RETURNS TABLE (
  id uuid,
  case_id uuid,
  source_type text,
  content text,
  similarity float,
  case_date date,
  case_type text,
  client_name text,
  lawyer_name text,
  is_signed boolean
)
LANGUAGE sql STABLE AS $$
  SELECT
    ch.id, ch.case_id, ch.source_type, ch.content,
    1 - (ch.embedding <=> query_embedding) AS similarity,
    cc.case_date, cc.case_type, cc.client_name, l.name AS lawyer_name,
    cc.is_signed
  FROM public.case_chunks ch
  JOIN public.consultation_cases cc ON cc.id = ch.case_id
  LEFT JOIN public.lawyers l ON l.id = cc.lawyer_id
  WHERE ch.embedding IS NOT NULL
    AND (
      cc.is_signed = false
      OR ch.source_type IN ('meeting_record', 'transcript')
    )
  ORDER BY ch.embedding <=> query_embedding
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION public.match_case_chunks TO authenticated;
