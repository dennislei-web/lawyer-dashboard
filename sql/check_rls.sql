select tablename, rowsecurity
from pg_tables
where schemaname='public'
  and tablename in ('advisor_transactions','advisor_cases','revenue_records','advisor_pending_cases');

select schemaname, tablename, policyname, roles, cmd, qual
from pg_policies
where tablename in ('advisor_transactions','advisor_cases','revenue_records');
