-- 允許主管會議系列 meeting_type
alter table meetings drop constraint if exists meetings_meeting_type_check;
alter table meetings add constraint meetings_meeting_type_check
  check (meeting_type = any (array['op_weekly','shareholder','monthly_all','partner_consult','one_on_one','mgmt_weekly','other']));
