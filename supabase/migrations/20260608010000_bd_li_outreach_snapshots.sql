-- 里長開發追蹤：每日 KPI 快照（用來算每週進度）
-- bd_li_outreach 每天整批 reload 且 talked/adopted/flyer 無日期，
-- 無法回頭算歷史，所以每天同步結尾記一筆當天的 5 個總數，往後長出週進度。

create table if not exists public.bd_li_outreach_snapshots (
  snapshot_date date primary key,
  total   integer not null default 0,  -- 里長總數
  visited integer not null default 0,  -- 有拜訪（visit1_date 有值）
  talked  integer not null default 0,  -- 完成洽談
  adopted integer not null default 0,  -- 採用
  flyer   integer not null default 0,  -- 放文宣
  created_at timestamptz not null default now()
);

alter table public.bd_li_outreach_snapshots enable row level security;

-- 白名單內的登入者可讀（與 bd_li_outreach / bd_li_oa_followers 一致）
drop policy if exists bd_li_snap_read on public.bd_li_outreach_snapshots;
create policy bd_li_snap_read on public.bd_li_outreach_snapshots
  for select to authenticated
  using (exists (
    select 1 from public.bd_li_access a
    where lower(a.email) = lower((auth.jwt() ->> 'email'))
  ));

-- 寫入由 Python 腳本以 service_role key 進行（繞過 RLS），故不開放 authenticated 寫入。
