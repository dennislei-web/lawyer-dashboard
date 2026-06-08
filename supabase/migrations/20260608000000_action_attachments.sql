-- 代辦事項 Action 附件：private bucket + admin 權限 + 欄位
-- 每個 meeting_action_items 可掛一個附件（不限檔型，上限 6MB）

insert into storage.buckets (id, name, public, file_size_limit)
values ('action-attachments', 'action-attachments', false, 6291456)
on conflict (id) do nothing;

-- meeting_action_items 是 admin-only，附件存取同樣只給 admin
drop policy if exists "action_attach_admin_all" on storage.objects;
create policy "action_attach_admin_all" on storage.objects
  for all
  using (bucket_id = 'action-attachments' and is_admin())
  with check (bucket_id = 'action-attachments' and is_admin());

alter table meeting_action_items
  add column if not exists attachment_path text,
  add column if not exists attachment_name text;
