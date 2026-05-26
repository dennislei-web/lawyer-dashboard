-- lawyers.feature_access TEXT[]
-- 控制「進階功能」的細部存取權（不同於 dashboard_access 控制整頁可見性）
--
-- 目前定義的 feature key：
--   consult_daily         — 諮詢分析 → 📊 每日累積 tab
--   revenue_daily         — 營運 → 每日累積 tab
--   consult_tracker_admin — 諮詢分析 → 1-on-1 追蹤頁的「全所 grand total」admin 視角
--   consult_health        — 諮詢分析 → 📊 未成案資料健康度 / 追單 AI 建議 tab
--
-- 預設空陣列 → 任何 role 都不會自動拿到這些功能，要在帳號管理頁逐一勾選。
-- 維持目前現狀：只有 dennis.lei@010.tw 有全部 4 個、CRM@zhelu.tw 有 consult_health。

ALTER TABLE public.lawyers
  ADD COLUMN IF NOT EXISTS feature_access TEXT[] NOT NULL DEFAULT '{}';

UPDATE public.lawyers
SET feature_access = ARRAY['consult_daily','revenue_daily','consult_tracker_admin','consult_health']
WHERE lower(email) = 'dennis.lei@010.tw';

UPDATE public.lawyers
SET feature_access = ARRAY['consult_health']
WHERE lower(email) = 'crm@zhelu.tw';

COMMENT ON COLUMN public.lawyers.feature_access IS
  '進階功能 key 陣列。可用 key：consult_daily / revenue_daily / consult_tracker_admin / consult_health。空陣列 = 沒有任何進階功能（包含 admin 也不會自動拿到）。';
