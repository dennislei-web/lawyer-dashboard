-- LINE OA webhook 收到的 follow / message 事件暫存
-- 4 個追蹤 OA 共用此表，靠 oa_id + user_id 為 PK
-- follow event → upsert row
-- message event → 若 matched_case_id IS NULL，嘗試從訊息文字抓姓名 match consultation_cases
-- 1 match 自動綁定 / 0 或多 match → 留在此表等下一則訊息或人工處理

CREATE TABLE IF NOT EXISTS public.line_pending_bindings (
  user_id text NOT NULL,
  oa_id text NOT NULL,
  oa_name text,
  followed_at timestamptz NOT NULL,
  last_message_at timestamptz,
  last_message_text text,
  last_extracted_name text,
  match_attempts int NOT NULL DEFAULT 0,
  matched_case_id uuid REFERENCES public.consultation_cases(id) ON DELETE SET NULL,
  matched_at timestamptz,
  matched_by text CHECK (matched_by IS NULL OR matched_by IN ('auto', 'manual')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, oa_id)
);

CREATE INDEX IF NOT EXISTS idx_line_pending_bindings_unmatched
  ON public.line_pending_bindings (followed_at DESC)
  WHERE matched_case_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_line_pending_bindings_matched_case
  ON public.line_pending_bindings (matched_case_id)
  WHERE matched_case_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.line_pending_bindings_touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_line_pending_bindings_updated_at ON public.line_pending_bindings;
CREATE TRIGGER trg_line_pending_bindings_updated_at
  BEFORE UPDATE ON public.line_pending_bindings
  FOR EACH ROW EXECUTE FUNCTION public.line_pending_bindings_touch_updated_at();

ALTER TABLE public.line_pending_bindings ENABLE ROW LEVEL SECURITY;

-- 律師/法務登入可讀（看待綁清單）
CREATE POLICY line_pending_bindings_select_authenticated ON public.line_pending_bindings
  FOR SELECT TO authenticated
  USING (true);

-- 律師/法務登入可更新（手動綁定寫 matched_case_id）
CREATE POLICY line_pending_bindings_update_authenticated ON public.line_pending_bindings
  FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (true);

-- INSERT / DELETE 只允許 service role（Edge Function）

COMMENT ON TABLE public.line_pending_bindings IS
  'LINE OA webhook 暫存：follow/message event 累積，用於把 userId 綁到 consultation_cases.line_chat_url';
COMMENT ON COLUMN public.line_pending_bindings.oa_id IS
  'LINE webhook body.destination，同時也是 chat.line.biz URL 的第一段 OA internal id';
COMMENT ON COLUMN public.line_pending_bindings.matched_by IS
  'auto=webhook 自動 match 到 / manual=法務在 dashboard 手動綁';
