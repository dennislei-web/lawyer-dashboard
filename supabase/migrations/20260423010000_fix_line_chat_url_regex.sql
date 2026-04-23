-- 放寬 line_chat_url 格式檢查：
-- LINE chat ID 可能是 U（個人）、C（群組）、R（多人聊天室）開頭，不只 U
-- 舊 constraint 只接受 U 會擋掉群組對話

ALTER TABLE public.consultation_cases
  DROP CONSTRAINT IF EXISTS line_chat_url_format;

ALTER TABLE public.consultation_cases
  ADD CONSTRAINT line_chat_url_format
  CHECK (
    line_chat_url IS NULL
    OR line_chat_url ~ '^https://chat\.line\.biz/U[0-9a-f]+/chat/[UCR][0-9a-f]+'
  );
