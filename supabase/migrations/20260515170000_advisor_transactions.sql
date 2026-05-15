-- 法顧對帳資訊（CRM /dashboard/advisor_transactions）
-- 法顧客戶儲值帳本 — 22 筆/月，含轉帳儲值、執行業務扣抵、事務所代繳等。
-- 跟 advisor_cases（成案口徑，從 Sheets 同步）是不同 SoT：
--   advisor_transactions = 現金 / 儲值流水（cash basis）
--   advisor_cases        = 成案 / 收費認列（accrual basis）

create table if not exists advisor_transactions (
  transaction_id    uuid primary key,
  record_date       date not null,
  amount            numeric not null default 0,
  point             numeric default 0,
  is_void           boolean not null default false,
  notes             text,
  payment_method    text,
  client_name       text,
  client_vat        text,
  subject_id        uuid,
  organization_id   uuid,
  case_id           uuid,
  contract_end_date date,
  is_legal_advisor  boolean,
  total_point       numeric,
  google_drive_link text,
  raw_subject       jsonb,
  synced_at         timestamptz not null default now()
);

create index if not exists idx_advisor_transactions_record_date on advisor_transactions(record_date);
create index if not exists idx_advisor_transactions_client_name on advisor_transactions(client_name);
create index if not exists idx_advisor_transactions_is_void on advisor_transactions(is_void);

comment on table advisor_transactions is
  '法顧客戶儲值帳本（CRM 法顧對帳資訊 /dashboard/advisor_transactions 爬下來）。現金流入口徑，非作廢的 amount 加總 = 全月實際法顧收款（儲值部分）。';
