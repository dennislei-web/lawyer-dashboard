-- ============================================================
--  跟進中案件：加 LINE OA 對話連結欄位
--  與 consultation_cases.line_chat_url 同樣的格式檢查
--  （URL 形式類似 https://chat.line.biz/U.../chat/{U|C|R}...）
-- ============================================================

ALTER TABLE advisor_pending_state
  ADD COLUMN IF NOT EXISTS line_chat_url        TEXT,
  ADD COLUMN IF NOT EXISTS line_chat_updated_at TIMESTAMPTZ;

ALTER TABLE advisor_pending_state
  DROP CONSTRAINT IF EXISTS advisor_pending_line_chat_url_format;

ALTER TABLE advisor_pending_state
  ADD CONSTRAINT advisor_pending_line_chat_url_format
  CHECK (
    line_chat_url IS NULL
    OR line_chat_url ~ '^https://chat\.line\.biz/U[0-9a-f]+/chat/[UCR][0-9a-f]+'
  );

COMMENT ON COLUMN advisor_pending_state.line_chat_url IS
  '跟進中案件的 LINE OA 對話連結（個人 U / 群組 C / 多人聊天室 R）';
COMMENT ON COLUMN advisor_pending_state.line_chat_updated_at IS
  'line_chat_url 最後更新時間（稽核用）';
