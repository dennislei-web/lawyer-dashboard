-- 里長開發追蹤快照：改為「每位負責人 × 每日」granularity
-- 原本只記全所總量，改成逐人一列（全所量 = 當天各人加總）。

truncate table public.bd_li_outreach_snapshots;

alter table public.bd_li_outreach_snapshots
  drop constraint bd_li_outreach_snapshots_pkey;

alter table public.bd_li_outreach_snapshots
  add column if not exists owner text not null default '';

alter table public.bd_li_outreach_snapshots
  add constraint bd_li_outreach_snapshots_pkey primary key (snapshot_date, owner);
