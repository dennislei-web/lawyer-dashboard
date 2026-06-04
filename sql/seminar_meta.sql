-- 講座場次層級資料(來自行銷雙週會議記錄) → 儀表板成效層
-- 每場 webinar 的廣告費 / 報名數 / 出席 / 加LINE，補在 lead 層之上：
--   廣告費 → 講座報名 → 出席 → 有諮詢意願(seminar_leads) → 聯繫 → 約成
--
-- seminar 欄要對應 seminar_leads.seminar(分頁清理名)。
-- ad_spend_est=true 代表會議記錄未列總額、用「AP報名數×CPL」推估，可手動覆蓋。
--
-- ⚠️ 在 Supabase SQL Editor 執行一次(建表+RLS+灌9場)。資料更新可直接改此表或重跑。

create table if not exists public.seminar_meta (
  seminar       text primary key,   -- 對應 seminar_leads.seminar
  topic         text,
  audience      text,               -- 2B / 2C
  fmt           text,               -- 線上 / 實體
  ad_spend      numeric,            -- 廣告花費
  ad_spend_est  boolean default false,
  cpl           numeric,            -- 單筆成本 / AP CPA
  reg_count     int,                -- 講座報名數(整場 webinar)
  attend_count  int,                -- 出席人數
  attend_rate   numeric,            -- 出席率(%)
  line_signups  int,                -- 當日加入 LINE@ 人數
  booked_doc    int,                -- 會議記錄記載的約成場次(參考)
  note          text,
  updated_at    timestamptz not null default now()
);

alter table public.seminar_meta enable row level security;
drop policy if exists seminar_meta_read on public.seminar_meta;
create policy seminar_meta_read on public.seminar_meta
  for select to authenticated using (public.seminar_has_access());

insert into public.seminar_meta
  (seminar, topic, audience, fmt, ad_spend, ad_spend_est, cpl, reg_count, attend_count, attend_rate, line_signups, booked_doc, note) values
  ('1140424離婚財產、0618遺囑講座致電','離婚財產(首場)','2C','線上', 5000,    false, 92.59,  537, 235, 43.76, 115, 24, '4/24 離婚財產;約成含LINE群發'),
  ('1140723親權講座致電',              '親權',          '2C','線上', 2819.3,  false, 128.15, 293, 127, 43.34,  78, null,'7/23 親權'),
  ('1140827侵配講座致電',              '侵害配偶權',    '2C','線上', 5001.17, false, 106.41, 374, 180, 52.22,  87, 6,   '8/27 外遇蒐證'),
  ('1140930詐騙講座聯繫',              '詐欺',          '2C','線上', 4658.5,  false, 58.97,  368, 191, 51.90,  99, 2,   '9/30 詐騙求償'),
  ('1141029離婚財產講座聯繫',          '離婚財產(2)',   '2C','線上', 5001.1,  false, 125.03, 317, 145, 45.74,  52, 3,   '10/29 受雙11排擠'),
  ('1141126不動產講座聯繫',            '不動產',        '2C','線上', 2444.2,  true,  43.15,  407, 207, 50.80, 108, null,'11/26 不動產糾紛;廣告費為中期推估'),
  ('1150205探視權講座聯繫',            '探視權/親權',   '2C','線上', 5001,    true,  89.31,  223,  91, 40.80,  31, null,'2/5 探視權;廣告費推估(56×89.31)'),
  ('1150528遺囑、財產規劃講座聯繫',     '遺囑/遺產規劃', '2C','線上', 7159,    true,  45.89,  498, 235, 47.19, 121, null,'5/28 遺囑;廣告費推估(156×45.89)'),
  ('1150601講座聯繫',                  '職場霸凌',      '2C','線上', 1795,    true,  11.58,  435, null,null,   null,null,'6/17 職場霸凌;宣傳中、尚未舉辦,廣告費推估(155×11.58)')
on conflict (seminar) do update set
  topic=excluded.topic, audience=excluded.audience, fmt=excluded.fmt,
  ad_spend=excluded.ad_spend, ad_spend_est=excluded.ad_spend_est, cpl=excluded.cpl,
  reg_count=excluded.reg_count, attend_count=excluded.attend_count,
  attend_rate=excluded.attend_rate, line_signups=excluded.line_signups,
  booked_doc=excluded.booked_doc, note=excluded.note, updated_at=now();
