-- ============================================
-- 喆律法律事務所 - 一次性完整設定
-- 在 Supabase SQL Editor 中執行此檔案
-- ============================================

-- ============================================
-- 1. 建立資料表
-- ============================================

CREATE TABLE lawyers (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  auth_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL DEFAULT 'lawyer' CHECK (role IN ('lawyer', 'admin')),
  office TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_lawyers_auth_user_id ON lawyers(auth_user_id);
CREATE INDEX idx_lawyers_email ON lawyers(email);

CREATE TABLE monthly_stats (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  lawyer_id UUID NOT NULL REFERENCES lawyers(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  consult_count INTEGER DEFAULT 0,
  signed_count INTEGER DEFAULT 0,
  sign_rate NUMERIC(5,2) DEFAULT 0,
  revenue NUMERIC(12,0) DEFAULT 0,
  collected NUMERIC(12,0) DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(lawyer_id, month)
);

CREATE INDEX idx_monthly_stats_lawyer_id ON monthly_stats(lawyer_id);
CREATE INDEX idx_monthly_stats_month ON monthly_stats(month);

CREATE TABLE consultation_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  lawyer_id UUID NOT NULL REFERENCES lawyers(id) ON DELETE CASCADE,
  consult_date DATE NOT NULL,
  case_number TEXT,
  office TEXT,
  brand TEXT,
  client_name TEXT,
  consult_method TEXT,
  service_type TEXT,
  sign_status TEXT,
  revenue NUMERIC(12,0) DEFAULT 0,
  collected NUMERIC(12,0) DEFAULT 0,
  is_counted BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(case_number)
);

CREATE INDEX idx_consultation_logs_lawyer_id ON consultation_logs(lawyer_id);
CREATE INDEX idx_consultation_logs_date ON consultation_logs(consult_date);

-- ============================================
-- 2. 自動更新 updated_at
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
-- 3. View: lawyer_summary
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
-- 4. Row Level Security (RLS)
-- ============================================

ALTER TABLE lawyers ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultation_logs ENABLE ROW LEVEL SECURITY;

-- lawyers
CREATE POLICY "lawyers_select_own" ON lawyers
  FOR SELECT USING (auth_user_id = auth.uid());

CREATE POLICY "lawyers_select_admin" ON lawyers
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM lawyers AS l WHERE l.auth_user_id = auth.uid() AND l.role = 'admin')
  );

CREATE POLICY "lawyers_insert_admin" ON lawyers
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM lawyers AS l WHERE l.auth_user_id = auth.uid() AND l.role = 'admin')
  );

CREATE POLICY "lawyers_update_admin" ON lawyers
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM lawyers AS l WHERE l.auth_user_id = auth.uid() AND l.role = 'admin')
  );

-- monthly_stats
CREATE POLICY "monthly_stats_select_own" ON monthly_stats
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM lawyers WHERE auth_user_id = auth.uid())
  );

CREATE POLICY "monthly_stats_select_admin" ON monthly_stats
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin')
  );

CREATE POLICY "monthly_stats_upsert_admin" ON monthly_stats
  FOR ALL USING (
    EXISTS (SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin')
  );

-- consultation_logs
CREATE POLICY "consultation_logs_select_own" ON consultation_logs
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM lawyers WHERE auth_user_id = auth.uid())
  );

CREATE POLICY "consultation_logs_select_admin" ON consultation_logs
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin')
  );

CREATE POLICY "consultation_logs_upsert_admin" ON consultation_logs
  FOR ALL USING (
    EXISTS (SELECT 1 FROM lawyers WHERE auth_user_id = auth.uid() AND role = 'admin')
  );

-- ============================================
-- 5. 插入管理員 + 全部律師資料
-- ============================================

INSERT INTO lawyers (name, email, role, office) VALUES
  ('雷皓明', 'dennis.lei@010.tw', 'admin', '喆律法律事務所');

INSERT INTO lawyers (name, email, role, office) VALUES
  ('劉奕靖', 'lawyer_liuyijing@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('劉明潔', 'lawyer_liumingjie@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('劉誠夫', 'lawyer_liuchengfu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('劉雅涵', 'lawyer_liuyahan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('吳柏慶', 'lawyer_wuboqing@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('嚴心吟', 'lawyer_yanxinyin@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('孫少輔', 'lawyer_sunshaofu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('廖懿涵', 'lawyer_liaoyihan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('張元毓', 'lawyer_zhangyuanyu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('張又仁', 'lawyer_zhangyouren@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('徐品軒', 'lawyer_xupinxuan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('徐棠娜', 'lawyer_xutangna@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('方心瑜', 'lawyer_fangxinyu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('李家泓', 'lawyer_lijiahong@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('李昭萱', 'lawyer_lizhaoxuan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('李杰峰', 'lawyer_lijiefeng@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('林昀',   'lawyer_linyun@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('林桑羽', 'lawyer_linsangyu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('柯雪莉', 'lawyer_kexueli@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('洪琬琪', 'lawyer_hongwanqi@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('王湘閔', 'lawyer_wangxiangmin@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('王郁萱', 'lawyer_wangyuxuan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('葉芷羽', 'lawyer_yezhiyu@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('蘇端雅', 'lawyer_suduanya@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('蘇萱',   'lawyer_suxuan@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('許煜婕', 'lawyer_xuyujie@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('許致維', 'lawyer_xuzhiwei@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('陳寧馨', 'lawyer_chenningxin@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('陶光星', 'lawyer_taoguangxing@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('黃惠群', 'lawyer_huanghuiqun@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('黃杰',   'lawyer_huangjie@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('黃顯皓', 'lawyer_huangxianhao@placeholder.com', 'lawyer', '喆律法律事務所'),
  ('黃馨儀', 'lawyer_huangxinyi@placeholder.com', 'lawyer', '喆律法律事務所');

-- ============================================
-- 6. 綁定 Auth 帳號（在 Dashboard 建立 Auth 使用者後執行）
-- ============================================
-- 步驟：
-- 1. 先在 Supabase Dashboard → Authentication → Users → Add User 建立帳號
-- 2. 然後執行以下 SQL：
--
-- UPDATE lawyers
-- SET auth_user_id = (SELECT id FROM auth.users WHERE email = 'dennis.lei@010.tw')
-- WHERE email = 'dennis.lei@010.tw';
