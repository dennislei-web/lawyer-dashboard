-- P1: 未成案追蹤表加 LINE OA 對話連結
-- 法務手動貼 LINE OA 後台對話深連結，律師點了直接跳 LINE OA 看歷程
-- RLS：沿用 cases_update_notes policy（所有 authenticated 律師皆可寫）

ALTER TABLE public.consultation_cases
  ADD COLUMN line_chat_url text,
  ADD COLUMN line_chat_updated_at timestamptz,
  ADD COLUMN line_chat_updated_by uuid REFERENCES public.lawyers(id);

-- CHECK constraint 依實際 URL pattern：
-- https://chat.line.biz/{OA_internal_id}/chat/{chat_id}
-- 其中 ID 為 U 開頭的 hex 字串
ALTER TABLE public.consultation_cases
  ADD CONSTRAINT line_chat_url_format
  CHECK (
    line_chat_url IS NULL
    OR line_chat_url ~ '^https://chat\.line\.biz/U[0-9a-f]+/chat/U[0-9a-f]+'
  );

COMMENT ON COLUMN public.consultation_cases.line_chat_url IS
  'LINE OA 後台對話深連結（法務手動貼入，供律師點擊跳轉查看跟進歷程）';
COMMENT ON COLUMN public.consultation_cases.line_chat_updated_at IS
  'line_chat_url 最後更新時間（稽核用）';
COMMENT ON COLUMN public.consultation_cases.line_chat_updated_by IS
  'line_chat_url 最後更新者 lawyer id（稽核用）';
