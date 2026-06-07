-- 🔁 諮詢未成案「Pipeline 狀態機」
-- 在 App 內單一來源的漏斗階段欄位，與 CRM 來源的 tracking_status 分開，
-- 避免雙來源狀態打架（見過往「簽約判斷雙來源陷阱」）。
-- 階段：待跟進 → 已聯繫 → 已約二諮 → 成案 / 放棄
-- pipeline_stage 只由前端未成案追蹤頁編輯；Python 同步腳本不應碰它。

alter table consultation_cases
  add column if not exists pipeline_stage    text,
  add column if not exists pipeline_stage_at timestamptz;

comment on column consultation_cases.pipeline_stage is
  'App 內漏斗階段（單一來源）：待跟進/已聯繫/已約二諮/成案/放棄。與 CRM 的 tracking_status 分開。';
comment on column consultation_cases.pipeline_stage_at is
  '最後一次變更 pipeline_stage 的時間，用於計算各階段停留時間。';

create index if not exists idx_consultation_cases_pipeline_stage
  on consultation_cases(pipeline_stage);
