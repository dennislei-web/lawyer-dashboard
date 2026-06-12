-- 委後服務角色函式加固（security advisor 警告修正）：
--   1. SECURITY DEFINER 函式固定 search_path，防 schema 劫持
--   2. 收回 anon / public 的 EXECUTE（authenticated 保留：RLS policy 評估以呼叫者身分執行函式）
CREATE OR REPLACE FUNCTION is_manager()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM lawyers
        WHERE auth_user_id = auth.uid() AND role IN ('manager', 'admin')
    );
$$;

CREATE OR REPLACE FUNCTION is_service_case_owner(p_case_id UUID)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM advisor_service_cases c
        JOIN lawyers l ON l.id = c.owner_id
        WHERE c.id = p_case_id AND l.auth_user_id = auth.uid()
    );
$$;

REVOKE EXECUTE ON FUNCTION is_manager() FROM anon, public;
REVOKE EXECUTE ON FUNCTION is_service_case_owner(UUID) FROM anon, public;
