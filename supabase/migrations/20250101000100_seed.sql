-- ============================================
-- 喆律法律事務所 律師名單（共 34 位）
-- email 欄位請替換成實際 email
-- auth_user_id 由 create_auth_users.py 自動填入
-- ============================================

-- 管理員帳號（雷皓明為主持律師，預設為管理員）
INSERT INTO lawyers (name, email, role, office) VALUES
  ('雷皓明', 'dennis.lei@010.tw', 'admin', '喆律法律事務所')
ON CONFLICT (email) DO NOTHING;

-- 律師帳號（共 33 位）
INSERT INTO lawyers (name, email, role, office) VALUES
  ('劉奕靖', 'REPLACE_EMAIL_01@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('劉明潔', 'REPLACE_EMAIL_02@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('劉誠夫', 'REPLACE_EMAIL_03@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('劉雅涵', 'REPLACE_EMAIL_04@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('吳柏慶', 'REPLACE_EMAIL_05@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('嚴心吟', 'REPLACE_EMAIL_06@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('孫少輔', 'REPLACE_EMAIL_07@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('廖懿涵', 'REPLACE_EMAIL_08@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('張元毓', 'REPLACE_EMAIL_09@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('張又仁', 'REPLACE_EMAIL_10@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('徐品軒', 'REPLACE_EMAIL_11@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('徐棠娜', 'REPLACE_EMAIL_12@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('方心瑜', 'REPLACE_EMAIL_13@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('李家泓', 'REPLACE_EMAIL_14@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('李昭萱', 'REPLACE_EMAIL_15@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('李杰峰', 'REPLACE_EMAIL_16@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('林昀',   'REPLACE_EMAIL_17@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('林桑羽', 'REPLACE_EMAIL_18@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('柯雪莉', 'REPLACE_EMAIL_19@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('洪琬琪', 'REPLACE_EMAIL_20@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('王湘閔', 'REPLACE_EMAIL_21@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('王郁萱', 'REPLACE_EMAIL_22@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('葉芷羽', 'REPLACE_EMAIL_23@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('蘇端雅', 'REPLACE_EMAIL_24@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('蘇萱',   'REPLACE_EMAIL_25@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('許煜婕', 'REPLACE_EMAIL_26@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('許致維', 'REPLACE_EMAIL_27@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('陳寧馨', 'REPLACE_EMAIL_28@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('陶光星', 'REPLACE_EMAIL_29@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('黃惠群', 'REPLACE_EMAIL_30@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('黃杰',   'REPLACE_EMAIL_31@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('黃顯皓', 'REPLACE_EMAIL_32@zhelv.com', 'lawyer', '喆律法律事務所'),
  ('黃馨儀', 'REPLACE_EMAIL_33@zhelv.com', 'lawyer', '喆律法律事務所')
ON CONFLICT (email) DO NOTHING;
