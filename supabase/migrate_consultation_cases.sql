-- ============================================
-- 遷移：consultation_cases 加入 case_number, client_name
-- 解決 UNIQUE(lawyer_id, case_date, case_type) 導致同日同類型案件被合併的問題
-- ============================================

-- 1. 新增欄位
ALTER TABLE public.consultation_cases
  ADD COLUMN IF NOT EXISTS case_number TEXT,
  ADD COLUMN IF NOT EXISTS client_name TEXT;

-- 2. 為現有無 case_number 的記錄產生唯一值
UPDATE public.consultation_cases
SET case_number = 'GEN_' || id::text
WHERE case_number IS NULL;

-- 3. 設為 NOT NULL
ALTER TABLE public.consultation_cases
  ALTER COLUMN case_number SET NOT NULL;

-- 4. 移除舊的 UNIQUE 約束
ALTER TABLE public.consultation_cases
  DROP CONSTRAINT IF EXISTS consultation_cases_lawyer_id_case_date_case_type_key;

-- 5. 加入新的 UNIQUE（案件編號唯一）
ALTER TABLE public.consultation_cases
  ADD CONSTRAINT consultation_cases_case_number_key UNIQUE (case_number);

-- 6. 加入索引加速查詢
CREATE INDEX IF NOT EXISTS idx_cases_case_number ON public.consultation_cases(case_number);
