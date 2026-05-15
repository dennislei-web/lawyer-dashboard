-- advisor_transactions RLS — 對齊 advisor_cases pattern
alter table advisor_transactions enable row level security;

create policy advisor_transactions_admin
  on advisor_transactions
  for all
  using (is_admin());

create policy advisor_transactions_select
  on advisor_transactions
  for select
  using (auth.uid() is not null);
