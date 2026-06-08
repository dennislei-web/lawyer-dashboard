-- 里民方案約成諮詢場次（每月）
-- 來源：法律010總表「里民方案」欄（目前先手動 seed，後續再接 sync）
-- 與 bd_li_outreach / bd_li_oa_followers 同一白名單(bd_li_access) RLS。

create table if not exists public.bd_li_consults (
  month       text primary key,          -- 'YYYY-MM'
  sessions    int  not null default 0,   -- 約成諮詢場次
  source      text not null default 'manual',  -- manual | sheet
  note        text,
  updated_at  timestamptz not null default now()
);

-- ── RLS：白名單可讀、可 upsert（與 bd_li_outreach 同 bd_li_access）──
alter table public.bd_li_consults enable row level security;

drop policy if exists bd_li_consults_read on public.bd_li_consults;
create policy bd_li_consults_read on public.bd_li_consults
  for select to authenticated
  using (exists (
    select 1 from public.bd_li_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  ));

drop policy if exists bd_li_consults_write on public.bd_li_consults;
create policy bd_li_consults_write on public.bd_li_consults
  for all to authenticated
  using (exists (
    select 1 from public.bd_li_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  ))
  with check (exists (
    select 1 from public.bd_li_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  ));

-- ── seed：法律010總表「里民方案」欄（2026-02 空白＝0，略過）──
insert into public.bd_li_consults (month, sessions, source) values
  ('2026-03', 1, 'manual'),
  ('2026-04', 5, 'manual'),
  ('2026-05', 1, 'manual'),
  ('2026-06', 1, 'manual')
on conflict (month) do update
  set sessions = excluded.sessions, source = excluded.source, updated_at = now();
