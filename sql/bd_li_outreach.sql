-- 里長開發記錄表 → 儀表板後端
-- 來源 Google Sheet「里長開發記錄表」(6 分頁 = 6 位負責同仁)
-- 每天 09:00 由 sync_li_outreach.py 全量 reload。

-- ── 主資料表(每列 = 一個里長 outreach 紀錄)──
create table if not exists public.bd_li_outreach (
  id               bigint generated always as identity primary key,
  owner            text not null,          -- 負責人(來源分頁名)
  region           text,                   -- 里(含縣市/區字串)
  chief            text,                   -- 里長姓名
  chief_phone      text,                   -- 連絡電話/手機(依璇名冊)
  chief_address    text,                   -- 里長辦公室地址(依璇名冊)
  social           text,                   -- 社群經營/社群
  expected_contact text,                   -- 預計聯繫時間(自由文字)
  visit1_date      text,
  visit1_note      text,
  visit2_date      text,
  visit2_note      text,
  visit3_date      text,
  visit3_note      text,
  visit_result     text,                   -- 拜訪結果
  tier             text,                   -- 維繫分級 A/B/C
  talked           boolean,                -- 完成洽談
  adopted          boolean,                -- 是否採用
  pulled_group     boolean,                -- 拉里長群組
  joined_community boolean,                -- 加入里社群
  flyer_placed     boolean,                -- 是否完成放置文宣
  flyer_deskcard   boolean,                -- 桌牌
  flyer_small      boolean,                -- 小文宣
  flyer_poster     boolean,                -- 海報
  loc_office       boolean,                -- 里長辦公室
  loc_service      boolean,                -- 里民服務中心
  loc_board        boolean,                -- 里民告示欄
  tracking         text,                   -- 追蹤與否(依璇名冊)
  note             text,                   -- 其餘註記
  raw              jsonb,                  -- 原始整列(header→value)備援
  row_index        int,                    -- 來源列號(可回溯)
  synced_at        timestamptz not null default now()
);

create index if not exists idx_bd_li_owner  on public.bd_li_outreach(owner);
create index if not exists idx_bd_li_region on public.bd_li_outreach(region);

-- ── 存取白名單(email)──RLS 用,與 lawyers 表解耦
create table if not exists public.bd_li_access (
  email     text primary key,
  name      text,
  added_at  timestamptz not null default now()
);

-- ── RLS:只有白名單內 email 的登入者可讀 ──
alter table public.bd_li_outreach enable row level security;
alter table public.bd_li_access   enable row level security;

drop policy if exists bd_li_read on public.bd_li_outreach;
create policy bd_li_read on public.bd_li_outreach
  for select to authenticated
  using (exists (
    select 1 from public.bd_li_access a
    where lower(a.email) = lower(auth.jwt() ->> 'email')
  ));

-- 讓登入者能查自己是否在白名單(供前端判斷 hasAccess)
drop policy if exists bd_li_access_self on public.bd_li_access;
create policy bd_li_access_self on public.bd_li_access
  for select to authenticated
  using (lower(email) = lower(auth.jwt() ->> 'email'));
