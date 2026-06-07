-- 🧪 諮詢優化「實驗日誌」
-- 每次調整諮詢做法都記為一個實驗：假設 → 介入 → 預期 → 結果 → 決策（留/砍/放大）
-- 這張表是「持續優化」的歷史記憶，避免重複試錯。

create table if not exists consultation_experiments (
  id            uuid primary key default gen_random_uuid(),
  title         text not null,                 -- 實驗短名
  hypothesis    text,                          -- 假設：我相信 X 能提高成案，因為…
  intervention  text,                          -- 介入內容：具體要律師/法務做什麼
  target        text,                          -- 對象：某律師 / 部門 / 全所
  metric        text,                          -- 觀測指標：用什麼數字判斷成敗
  prediction    text,                          -- 預期結果
  start_date    date,
  end_date      date,
  result        text,                          -- 實際結果
  decision      text not null default '進行中', -- 進行中 / 留 / 砍 / 放大
  source_pattern text,                         -- 來源：對應 SOP 引擎哪個失敗類別（選填）
  created_by    uuid references lawyers(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table consultation_experiments is '諮詢優化實驗日誌：假設→介入→結果→決策的閉環記錄';

-- updated_at 自動更新
create or replace function set_consultation_experiments_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_consultation_experiments_updated_at on consultation_experiments;
create trigger trg_consultation_experiments_updated_at
  before update on consultation_experiments
  for each row execute function set_consultation_experiments_updated_at();

-- RLS：登入者可讀；admin 可寫（沿用專案既有 is_admin() helper）
alter table consultation_experiments enable row level security;

drop policy if exists consultation_experiments_read on consultation_experiments;
create policy consultation_experiments_read
  on consultation_experiments for select
  using (auth.uid() is not null);

drop policy if exists consultation_experiments_write on consultation_experiments;
create policy consultation_experiments_write
  on consultation_experiments for all
  using (is_admin()) with check (is_admin());

create index if not exists idx_consultation_experiments_decision on consultation_experiments(decision);
create index if not exists idx_consultation_experiments_start on consultation_experiments(start_date desc);
