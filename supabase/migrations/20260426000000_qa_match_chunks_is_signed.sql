-- AI 問答的 cited chunks 顯示需要 is_signed（成案標記），給律師判斷該片段是否來自最終成案案件
-- 沿用 20260422000000_qa_schema.sql 的 match_case_chunks，加上 is_signed 欄位

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
  ORDER BY ch.embedding <=> query_embedding
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION public.match_case_chunks TO authenticated;
