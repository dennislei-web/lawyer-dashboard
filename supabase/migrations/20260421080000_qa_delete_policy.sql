-- 加 DELETE policy 讓 admin / manager / 發問人本人可刪自己的 QA
-- (原 20260422 migration 只有 SELECT / INSERT / UPDATE，沒有 DELETE)

CREATE POLICY "qa_entries_delete_own_or_admin" ON public.qa_entries
  FOR DELETE TO authenticated
  USING (
    asked_by = (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() IN ('admin', 'manager')
  );
