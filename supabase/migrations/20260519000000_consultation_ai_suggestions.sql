-- ============================================================
-- 接案同仁追單 AI 建議表（僅雷皓明可見）
-- ============================================================
-- 目的：對每件未成案，AI 生成下一步追單建議（時機 / 話術 / 強調點）
-- 接案同仁可照著做、雷皓明可評分以追蹤 AI 品質
-- 權限：僅 dennis.lei@010.tw 可讀/寫（沿用 consultation_tracker 模式）

CREATE TABLE IF NOT EXISTS consultation_ai_suggestions (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id            UUID NOT NULL UNIQUE
                       REFERENCES consultation_cases(id) ON DELETE CASCADE,

  -- AI 建議內容（結構化欄位 + 完整 JSON）
  urgency            TEXT,                    -- high | medium | low | none
  timing             TEXT,                    -- 「今天傍晚」「這週四前」「再等一週」
  suggested_message  TEXT,                    -- 可直接複製貼 LINE 的話術
  emphasis_points    TEXT,                    -- 要強調的點
  reasoning          TEXT,                    -- 為什麼這樣建議（一句話）
  full_response      JSONB,                   -- 完整 LLM 結構化回覆（含上述 + 額外欄位）

  -- 元資料（追蹤資料來源與模型版本）
  data_sources       JSONB,                   -- {has_lawyer_notes, has_tracking_notes, has_line_url, line_msg_count, ...}
  model              TEXT,                    -- claude-opus-4-7 / inline-opus / etc
  prompt_version     TEXT,                    -- v1 / v2 ...（方便 ablation）
  generated_at       TIMESTAMPTZ DEFAULT now(),

  -- Dennis 評分（觀察 AI 品質）
  rating             TEXT,                    -- adopted | edited | rejected | null
  rating_at          TIMESTAMPTZ,
  rating_notes       TEXT,                    -- 你可以留評語
  edited_message     TEXT                     -- 若 rating='edited' 存編輯後的話術
);

CREATE INDEX IF NOT EXISTS idx_ai_sugg_generated ON consultation_ai_suggestions(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_sugg_rating ON consultation_ai_suggestions(rating);
CREATE INDEX IF NOT EXISTS idx_ai_sugg_urgency ON consultation_ai_suggestions(urgency);

-- ============================================================
-- RLS：僅雷皓明 (dennis.lei@010.tw) 能讀/寫
-- ============================================================
ALTER TABLE consultation_ai_suggestions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ai_sugg_dennis_only ON consultation_ai_suggestions;
CREATE POLICY ai_sugg_dennis_only ON consultation_ai_suggestions
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lawyers.email = 'dennis.lei@010.tw'
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lawyers.email = 'dennis.lei@010.tw'
    )
  );

-- service_role 寫入（Python 批次腳本用）— 不需 policy，service key 繞 RLS

COMMENT ON TABLE consultation_ai_suggestions IS
  '接案同仁追單 AI 建議：對每件未成案，由 LLM 綜合 lawyer_notes/tracking_notes/LINE 對話生成下一步建議；僅雷皓明可見';
