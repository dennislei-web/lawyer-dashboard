-- 雷律師 廣告投放/LINE 成效追蹤 → 儀表板後端
-- 來源 Google Sheet「喆律 - 雷律師 ｜預算｜成效」分頁「上線至今」(welly 行銷團隊維護，每天自動從 FB 更新)
-- 每天 09:00 由 sync_marketing.py 全量 reload。

-- ── 月成效表 (「上線至今」cols A-G) ──
create table if not exists public.mkt_monthly (
  month            text primary key,        -- '2025/08'
  total_spend      numeric,                 -- 廣告總花費
  lead_spend       numeric,                 -- 廣告名單花費
  leads            int,                     -- 廣告名單數
  cpl              numeric,                 -- CPL 每名單成本
  line_link_spend  numeric,                 -- 廣告LINE連結點擊花費
  line_link_clicks int,                     -- LINE連結點擊次數
  synced_at        timestamptz not null default now()
);

-- ── 雙周 LINE@ 成長表 (「上線至今」cols I-P) ──
create table if not exists public.mkt_biweekly (
  period       text primary key,            -- '5/13-5/28(10:00)'
  period_end   date,                        -- 解析期末日(排序用)
  contacted    int,                         -- 實際聯繫上名單
  cpl          numeric,                     -- CPL
  line_added   int,                         -- 加入LINE@ (期間新增)
  line_total   int,                         -- 目前LINE@人數 (累計)
  line_cpa     numeric,                     -- 加入LINE@ CPA (累計總花費攤提)
  appts_closed int,                         -- 約成客戶
  appt_cpa     numeric,                     -- 約成 CPA
  synced_at    timestamptz not null default now()
);

-- ── 月約訪場次 (從「雙周報」週報回覆文字解析) ──
create table if not exists public.mkt_appointments (
  month         text primary key,           -- '2025-10'
  appointments  int,                        -- 該月實際約訪場次
  synced_at     timestamptz not null default now()
);

-- ── 存取白名單(email) ── RLS 用,與 lawyers 表解耦,與 bd_li_access 同模式
create table if not exists public.mkt_access (
  email     text primary key,
  name      text,
  added_at  timestamptz not null default now()
);

-- ── RLS:只有白名單內 email 的登入者可讀 ──
alter table public.mkt_monthly      enable row level security;
alter table public.mkt_biweekly     enable row level security;
alter table public.mkt_appointments enable row level security;
alter table public.mkt_access       enable row level security;

create or replace function public.mkt_has_access() returns boolean
  language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.mkt_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  );
$$;

drop policy if exists mkt_monthly_read on public.mkt_monthly;
create policy mkt_monthly_read on public.mkt_monthly
  for select to authenticated using (public.mkt_has_access());

drop policy if exists mkt_biweekly_read on public.mkt_biweekly;
create policy mkt_biweekly_read on public.mkt_biweekly
  for select to authenticated using (public.mkt_has_access());

drop policy if exists mkt_appointments_read on public.mkt_appointments;
create policy mkt_appointments_read on public.mkt_appointments
  for select to authenticated using (public.mkt_has_access());

-- 讓登入者能查自己是否在白名單(供前端判斷 hasAccess)
drop policy if exists mkt_access_self on public.mkt_access;
create policy mkt_access_self on public.mkt_access
  for select to authenticated
  using (lower(email) = lower(auth.jwt() ->> 'email'));

-- ── 種子:雷皓明 ──
insert into public.mkt_access (email, name) values
  ('dennis.lei@010.tw', '雷皓明')
on conflict (email) do nothing;
