-- ============================================
-- crm_cases  CRM 案件主檔（從 crm.lawyer 同步）
-- 來源：/dashboard/case_lists (list) + /api/cases/{id} (detail)
-- ============================================

CREATE TABLE IF NOT EXISTS public.crm_cases (
  case_id              UUID PRIMARY KEY,
  serial_number        TEXT NOT NULL UNIQUE,

  -- 狀態
  aasm_state           TEXT,                    -- appointed / unappointed / pending / closed / unconcluded / canceled
  state_category       TEXT GENERATED ALWAYS AS (
    CASE
      WHEN aasm_state = 'appointed'                                  THEN 'in_progress'      -- 承辦中（已委任）
      WHEN aasm_state IN ('pending', 'closed')                       THEN 'completed'        -- 已處理完成（待結案 + 結案）
      WHEN aasm_state IN ('unappointed', 'unconcluded', 'canceled')  THEN 'pre_engagement' -- 未進入承辦（未委任 + 未成案 + 取消）
      ELSE 'unknown'
    END
  ) STORED,

  -- 案件資訊
  clients              TEXT,
  adversaries          TEXT,
  cause_of_action      TEXT,
  case_type            TEXT,                    -- list 頁的 type 欄位 (Case / 其他)
  note                 TEXT,
  internal_note        TEXT,
  meeting_note         TEXT,
  unappointed_note     TEXT,

  -- 組織歸屬
  office_name          TEXT,
  council_office_name  TEXT,
  department_name      TEXT,
  group_id             UUID,

  -- 律師與成員（存陣列）
  council_lawyers      TEXT[],                  -- 諮詢律師
  assigned_members     TEXT[],                  -- 接案律師
  litigation_lawyers   TEXT[],                  -- 訴訟律師
  pleading_lawyers     TEXT[],                  -- 書狀律師
  complaint_lawyers    TEXT[],                  -- 起訴律師
  in_court_lawyers     TEXT[],                  -- 出庭律師
  managers             TEXT[],                  -- 客戶經理
  clerks               TEXT[],                  -- 書記
  client_sources       TEXT[],                  -- 客戶來源

  -- 標籤
  case_labels          TEXT[],
  case_tags            TEXT[],

  -- 時間軸（CRM 端各狀態進入時間）
  crm_created_at       TIMESTAMPTZ,             -- 案件建立
  crm_updated_at       TIMESTAMPTZ,             -- CRM 最後更新
  appointed_at         TIMESTAMPTZ,             -- 委任時間
  first_appointed_at   TIMESTAMPTZ,             -- 首次委任
  pending_at           TIMESTAMPTZ,             -- 進入待結案
  closed_at            TIMESTAMPTZ,             -- 結案
  canceled_at          TIMESTAMPTZ,             -- 取消
  unconcluded_at       TIMESTAMPTZ,             -- 未成案
  unappointed_at       TIMESTAMPTZ,             -- 解除委任

  -- 列表頁額外欄位
  last_of_record       TEXT,                    -- 最近一次案件歷程
  last_of_court_record TEXT,                    -- 上次庭期
  next_of_court_record TEXT,                    -- 下次庭期

  -- 金額（如有）
  price_target         NUMERIC,

  -- 同步 metadata
  synced_at            TIMESTAMPTZ DEFAULT now(),
  detail_synced_at     TIMESTAMPTZ              -- detail API 最後同步時間
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_crm_cases_state         ON public.crm_cases(aasm_state);
CREATE INDEX IF NOT EXISTS idx_crm_cases_state_cat     ON public.crm_cases(state_category);
CREATE INDEX IF NOT EXISTS idx_crm_cases_closed_at     ON public.crm_cases(closed_at);
CREATE INDEX IF NOT EXISTS idx_crm_cases_crm_created   ON public.crm_cases(crm_created_at);
CREATE INDEX IF NOT EXISTS idx_crm_cases_office        ON public.crm_cases(office_name);
CREATE INDEX IF NOT EXISTS idx_crm_cases_department    ON public.crm_cases(department_name);
CREATE INDEX IF NOT EXISTS idx_crm_cases_detail_synced ON public.crm_cases(detail_synced_at);

-- ============================================
-- RLS：登入即可讀；admin 可改
-- ============================================
ALTER TABLE public.crm_cases ENABLE ROW LEVEL SECURITY;

CREATE POLICY "crm_cases_select" ON public.crm_cases
  FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY "crm_cases_modify_admin" ON public.crm_cases
  FOR ALL USING (public.get_my_role() = 'admin');

-- ============================================
-- sync_status row：crm_cases 同步狀態
-- ============================================
INSERT INTO public.sync_status (id, status, message)
VALUES ('crm_cases', 'pending', '尚未首爬')
ON CONFLICT (id) DO NOTHING;
