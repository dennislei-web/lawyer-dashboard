-- 每月例行（Phase 3）：跟追歷程新增「每月報告」事件型別，
-- 用於勾稽 SOP 每月底時數表/每月報告寄送狀態
ALTER TABLE advisor_case_events DROP CONSTRAINT advisor_case_events_event_type_check;
ALTER TABLE advisor_case_events ADD CONSTRAINT advisor_case_events_event_type_check
  CHECK (event_type IN ('note','call','meeting','hours','renewal','stage_change','monthly_report'));
