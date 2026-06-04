-- 講座報名 → 諮詢約成 轉化追蹤 → 儀表板後端
-- 來源 Google Sheet「講座報名/後續處理」分頁 gid=438665286（客服團隊維護）
-- 每天 09:00 由 sync_seminar.py 全量 reload。
--
-- 轉化漏斗：報名 → 利衝建檔 → 聯繫完成 → 導入 LINE@ → 約成諮詢
--
-- ⚠️ 此檔需在 Supabase Dashboard → SQL Editor 手動執行一次（建表 + RLS）。
--    執行後再跑 scripts/sync_seminar.py 灌資料。

-- ── 線索明細表（每位報名者一列） ──
create table if not exists public.seminar_leads (
  lead_key       text primary key,   -- 唯一鍵（原始編號，缺漏時用 seq_N）
  lead_no        text,               -- 原始編號 '緩分1' / '16'
  row_index      int,                -- 在試算表中的列序（排序用）
  reg_at         text,               -- 填表時間原字串 '2026/5/28 0:0:0'
  reg_date       date,               -- 解析後的報名日（趨勢用）
  name           text,               -- 姓名
  email          text,
  phone          text,
  has_need       boolean,            -- 諮詢需求 = 是
  contact_channel text,              -- 聯繫管道（電子郵件/LINE/電話，可多選）
  line_id        text,
  contact_time   text,               -- 方便聯繫時間
  help_needed    text,               -- 需要律師如何協助（自由文字）
  query_date     text,               -- 利衝查詢日期
  name_query     text,               -- 姓名查詢結果（無收錄/有同名者/暱稱/已收錄）
  phone_query    text,               -- 電話查詢結果
  special_status text,               -- 特殊狀況（已委/已諮/利衝等）
  owner          text,               -- 負責同仁
  contact_notes  text,               -- 聯繫狀況摘要
  contacted      boolean,            -- 聯繫完成
  conflict_filed boolean,            -- 利衝建檔
  line_url       text,               -- 導入 LINE@ 聊天室連結（有值=已導入）
  booked         boolean,            -- 是否約成
  booking_info   text,               -- 預約資訊
  synced_at      timestamptz not null default now()
);

create index if not exists seminar_leads_reg_date_idx on public.seminar_leads (reg_date);

-- ── 存取白名單(email) ── RLS 用，與 lawyers 表解耦，與 mkt_access 同模式
create table if not exists public.seminar_access (
  email     text primary key,
  name      text,
  added_at  timestamptz not null default now()
);

-- ── RLS：只有白名單內 email 的登入者可讀 ──
alter table public.seminar_leads  enable row level security;
alter table public.seminar_access enable row level security;

create or replace function public.seminar_has_access() returns boolean
  language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.seminar_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  );
$$;

drop policy if exists seminar_leads_read on public.seminar_leads;
create policy seminar_leads_read on public.seminar_leads
  for select to authenticated using (public.seminar_has_access());

-- 讓登入者能查自己是否在白名單（供前端判斷 hasAccess）
drop policy if exists seminar_access_self on public.seminar_access;
create policy seminar_access_self on public.seminar_access
  for select to authenticated
  using (lower(email) = lower(auth.jwt() ->> 'email'));

-- ── 種子：管理者 + CRM ──
insert into public.seminar_access (email, name) values
  ('dennis.lei@010.tw', '雷皓明'),
  ('CRM@zhelu.tw',      'CRM')
on conflict (email) do nothing;
