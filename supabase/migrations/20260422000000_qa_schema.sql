-- ============================================
-- P2 · AI QA 知識庫 schema
-- Embedding provider: Voyage AI voyage-law-2 (1024 dim)
-- ============================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- 1) case_chunks：過往諮詢語料的 chunk + embedding
-- ------------------------------------------------------------
CREATE TABLE public.case_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES public.consultation_cases(id) ON DELETE CASCADE,
  source_type text NOT NULL
    CHECK (source_type IN (
      'meeting_record', 'transcript',
      'llm_strength', 'llm_failure_reason', 'llm_missed_opp',
      'llm_improvement', 'llm_pattern'
    )),
  chunk_index int NOT NULL,
  content text NOT NULL,
  token_count int,
  embedding vector(1024),
  created_at timestamptz DEFAULT now(),
  UNIQUE (case_id, source_type, chunk_index)
);

CREATE INDEX case_chunks_embedding_idx
  ON public.case_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX case_chunks_case_id_idx ON public.case_chunks (case_id);

ALTER TABLE public.case_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "case_chunks_select_logged_in" ON public.case_chunks
  FOR SELECT TO authenticated USING (true);
-- 寫入只由 service_role（Python script、Edge Function）進行，不設 INSERT/UPDATE policy

-- ------------------------------------------------------------
-- 2) qa_entries：QA 知識庫主表
-- ------------------------------------------------------------
CREATE TABLE public.qa_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asked_by uuid NOT NULL REFERENCES public.lawyers(id),
  scenario text NOT NULL CHECK (char_length(scenario) BETWEEN 5 AND 300),
  scenario_embedding vector(1024),
  ai_answer text,
  ai_reasoning text,
  source_chunk_ids uuid[] DEFAULT '{}',
  tags text[] DEFAULT '{}',
  lawyer_refined_answer text,
  refined_by uuid REFERENCES public.lawyers(id),
  refined_at timestamptz,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX qa_entries_embedding_idx
  ON public.qa_entries USING ivfflat (scenario_embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX qa_entries_created_at_idx ON public.qa_entries (created_at DESC);
CREATE INDEX qa_entries_tags_idx ON public.qa_entries USING GIN (tags);

ALTER TABLE public.qa_entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "qa_entries_select_all_logged_in" ON public.qa_entries
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "qa_entries_insert_self" ON public.qa_entries
  FOR INSERT TO authenticated
  WITH CHECK (
    asked_by = (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
  );

CREATE POLICY "qa_entries_update_own_or_admin" ON public.qa_entries
  FOR UPDATE TO authenticated
  USING (
    asked_by = (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() IN ('admin', 'manager')
  );

-- ------------------------------------------------------------
-- 3) qa_ratings：👍 / 👎
-- ------------------------------------------------------------
CREATE TABLE public.qa_ratings (
  qa_id uuid NOT NULL REFERENCES public.qa_entries(id) ON DELETE CASCADE,
  lawyer_id uuid NOT NULL REFERENCES public.lawyers(id),
  rating smallint NOT NULL CHECK (rating IN (-1, 1)),
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (qa_id, lawyer_id)
);

ALTER TABLE public.qa_ratings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "qa_ratings_select" ON public.qa_ratings
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "qa_ratings_insert_self" ON public.qa_ratings
  FOR INSERT TO authenticated
  WITH CHECK (
    lawyer_id = (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
  );

CREATE POLICY "qa_ratings_update_self" ON public.qa_ratings
  FOR UPDATE TO authenticated
  USING (
    lawyer_id = (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
  );

-- ------------------------------------------------------------
-- 4) 自動更新 consultation_cases.updated_at
--    讓 Python script 的增量 re-embedding 邏輯能抓到 llm_analysis 變更
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.bump_consultation_cases_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'consultation_cases'
      AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE public.consultation_cases ADD COLUMN updated_at timestamptz DEFAULT now();
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_consultation_cases_updated_at ON public.consultation_cases;
CREATE TRIGGER trg_consultation_cases_updated_at
  BEFORE UPDATE ON public.consultation_cases
  FOR EACH ROW EXECUTE FUNCTION public.bump_consultation_cases_updated_at();

CREATE INDEX IF NOT EXISTS consultation_cases_updated_at_idx
  ON public.consultation_cases (updated_at);

-- ------------------------------------------------------------
-- 5) 自動更新 qa_entries.updated_at
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.bump_qa_entries_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_qa_entries_updated_at ON public.qa_entries;
CREATE TRIGGER trg_qa_entries_updated_at
  BEFORE UPDATE ON public.qa_entries
  FOR EACH ROW EXECUTE FUNCTION public.bump_qa_entries_updated_at();

-- ------------------------------------------------------------
-- 6) Vector search helper functions
-- ------------------------------------------------------------

-- 搜相似的既有 QA（題 4：相同問題直接貼）
CREATE OR REPLACE FUNCTION public.match_qa_entries(
  query_embedding vector(1024),
  match_threshold float DEFAULT 0.82,
  match_count int DEFAULT 3
)
RETURNS TABLE (
  id uuid,
  scenario text,
  ai_answer text,
  lawyer_refined_answer text,
  asked_by uuid,
  asked_by_name text,
  tags text[],
  created_at timestamptz,
  similarity float
)
LANGUAGE sql STABLE AS $$
  SELECT
    qa.id, qa.scenario, qa.ai_answer, qa.lawyer_refined_answer,
    qa.asked_by, l.name AS asked_by_name, qa.tags, qa.created_at,
    1 - (qa.scenario_embedding <=> query_embedding) AS similarity
  FROM public.qa_entries qa
  LEFT JOIN public.lawyers l ON l.id = qa.asked_by
  WHERE qa.scenario_embedding IS NOT NULL
    AND 1 - (qa.scenario_embedding <=> query_embedding) > match_threshold
  ORDER BY qa.scenario_embedding <=> query_embedding
  LIMIT match_count;
$$;

-- 搜相似的 case_chunk（RAG 主檢索）
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
  lawyer_name text
)
LANGUAGE sql STABLE AS $$
  SELECT
    ch.id, ch.case_id, ch.source_type, ch.content,
    1 - (ch.embedding <=> query_embedding) AS similarity,
    cc.case_date, cc.case_type, cc.client_name, l.name AS lawyer_name
  FROM public.case_chunks ch
  JOIN public.consultation_cases cc ON cc.id = ch.case_id
  LEFT JOIN public.lawyers l ON l.id = cc.lawyer_id
  WHERE ch.embedding IS NOT NULL
  ORDER BY ch.embedding <=> query_embedding
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION public.match_qa_entries TO authenticated;
GRANT EXECUTE ON FUNCTION public.match_case_chunks TO authenticated;
