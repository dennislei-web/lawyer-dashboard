-- ============================================
-- 喆律法律事務所 諮詢分析儀表板
-- Supabase Schema & Row Level Security
-- ============================================

-- ============================================
-- 1. lawyers 律師基本資料表
-- ============================================
CREATE TABLE lawyers (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  auth_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL DEFAULT 'lawyer' CHECK (role IN ('lawyer', 'admin')),
  office TEXT,              -- 所屬事務所（接案所）
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 建立 auth_user_id 索引，加速 RLS 查詢
CREATE INDEX idx_lawyers_auth_user_id ON lawyers(auth_user_id);
CREATE INDEX idx_lawyers_email ON lawyers(email);

-- ============================================
-- 2. monthly_stats 每月諮詢統計
-- ============================================
CREATE TABLE monthly_stats (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  lawyer_id UUID NOT NULL REFERENCES lawyers(id) ON DELETE CASCADE,
  month TEXT NOT NULL,            -- 格式: '2026-03'
  consult_count INTEGER DEFAULT 0,
  signed_count INTEGER DEFAULT 0,
  sign_rate NUMERIC(5,2) DEFAULT 0,  -- 百分比, e.g. 45.50
  revenue NUMERIC(12,0) DEFAULT 0,   -- 應收金額
  collected NUMERIC(12,0) DEFAULT 0, -- 已收金額
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  UNIQUE(lawyer_id, month)  -- 每位律師每月只有一筆
);

CREATE INDEX idx_monthly_stats_lawyer_id ON monthly_stats(lawyer_id);
CREATE INDEX idx_monthly_stats_month ON monthly_stats(month);

-- ============================================
-- 3. consultation_logs 逐筆諮詢記錄（選配）
-- ============================================
CREATE TABLE consultation_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  lawyer_id UUID NOT NULL REFERENCES lawyers(id) ON DELETE CASCADE,
  consult_date DATE NOT NULL,
  case_number TEXT,               -- 案件編號
  office TEXT,                    -- 接案所
  brand TEXT,                     -- 品牌
  client_name TEXT,               -- 當事人
  consult_method TEXT,            -- 諮詢方式
  service_type TEXT,              -- 服務項目
  sign_status TEXT,               -- 簽約狀態
  revenue NUMERIC(12,0) DEFAULT 0,
  collected NUMERIC(12,0) DEFAULT 0,
  is_counted BOOLEAN DEFAULT true, -- 是否列入計算
  created_at TIMESTAMPTZ DEFAULT now(),

  UNIQUE(case_number)  -- 案件編號唯一
);

CREATE INDEX idx_consultation_logs_lawyer_id ON consultation_logs(lawyer_id);
CREATE INDEX idx_consultation_logs_date ON consultation_logs(consult_date);

-- ============================================
-- 4. updated_at 自動更新 trigger
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER lawyers_updated_at
  BEFORE UPDATE ON lawyers
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER monthly_stats_updated_at
  BEFORE UPDATE ON monthly_stats
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 5. View: lawyer_summary 律師累計彙總
--    （取代原本的 CONSULT_STATS）
-- ============================================
CREATE OR REPLACE VIEW lawyer_summary AS
SELECT
  l.id AS lawyer_id,
  l.name,
  l.office,
  COALESCE(SUM(ms.consult_count), 0) AS total_consults,
  COALESCE(SUM(ms.signed_count), 0) AS total_signed,
  CASE
    WHEN SUM(ms.consult_count) > 0
    THEN ROUND(SUM(ms.signed_count)::NUMERIC / SUM(ms.consult_count) * 100, 2)
    ELSE 0
  END AS sign_rate,
  COALESCE(SUM(ms.revenue), 0) AS total_revenue,
  COALESCE(SUM(ms.collected), 0) AS total_collected
FROM lawyers l
LEFT JOIN monthly_stats ms ON l.id = ms.lawyer_id
WHERE l.is_active = true
GROUP BY l.id, l.name, l.office;

-- ============================================
-- 6. Row Level Security (RLS) 設定
-- ============================================

-- 啟用 RLS
ALTER TABLE lawyers ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultation_logs ENABLE ROW LEVEL SECURITY;

-- ----- lawyers 表 -----

-- 律師只能看到自己的資料
CREATE POLICY "lawyers_select_own" ON lawyers
  FOR SELECT USING (
    auth_user_id = auth.uid()
  );

-- 管理員可以看到所有律師
CREATE POLICY "lawyers_select_admin" ON lawyers
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.role = 'admin'
    )
  );

-- 只有管理員可以新增/修改律師
CREATE POLICY "lawyers_insert_admin" ON lawyers
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.role = 'admin'
    )
  );

CREATE POLICY "lawyers_update_admin" ON lawyers
  FOR UPDATE USING (
    EXISTS (
      SELECT 1 FROM lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.role = 'admin'
    )
  );

-- ----- monthly_stats 表 -----

-- 律師只能看自己的月統計
CREATE POLICY "monthly_stats_select_own" ON monthly_stats
  FOR SELECT USING (
    lawyer_id IN (
      SELECT id FROM lawyers WHERE auth_user_id = auth.uid()
    )
  );

-- 管理員可以看全部
CREATE POLICY "monthly_stats_select_admin" ON monthly_stats
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin'
    )
  );

-- ----- consultation_logs 表 -----

-- 律師只能看自己的諮詢記錄
CREATE POLICY "consultation_logs_select_own" ON consultation_logs
  FOR SELECT USING (
    lawyer_id IN (
      SELECT id FROM lawyers WHERE auth_user_id = auth.uid()
    )
  );

-- 管理員可以看全部
CREATE POLICY "consultation_logs_select_admin" ON consultation_logs
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin'
    )
  );

-- ============================================
-- 7. Service Role 寫入權限
--    Python update_script 使用 service_role key，
--    會繞過 RLS，所以不需要額外的 INSERT/UPDATE policy。
--    如需透過前端管理員寫入，加以下 policy：
-- ============================================

CREATE POLICY "monthly_stats_upsert_admin" ON monthly_stats
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin'
    )
  );

CREATE POLICY "consultation_logs_upsert_admin" ON consultation_logs
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin'
    )
  );
