-- 建立重設密碼的 RPC 函數
-- 使用 Supabase 內建的 auth.users 表直接更新密碼 hash
-- 只有 admin 角色才能呼叫

CREATE OR REPLACE FUNCTION public.admin_reset_password(target_user_id UUID, new_password TEXT)
RETURNS BOOLEAN AS $$
DECLARE
  caller_role TEXT;
BEGIN
  -- 檢查呼叫者是否為 admin
  SELECT role INTO caller_role FROM public.lawyers WHERE auth_user_id = auth.uid();
  IF caller_role IS NULL OR caller_role != 'admin' THEN
    RAISE EXCEPTION 'Permission denied: admin only';
  END IF;

  -- 使用 Supabase 內建的 auth schema 更新密碼
  UPDATE auth.users
  SET encrypted_password = crypt(new_password, gen_salt('bf')),
      updated_at = now()
  WHERE id = target_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'User not found';
  END IF;

  RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
