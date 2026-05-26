-- 補進 32 位「lawyers 表查無但仍在職」的同仁
-- 9 位 legal_staff（呂姿青等）+ 23 位 lawyer
-- email 暫不填，is_active=true，departed_at=NULL

INSERT INTO lawyers (name, role, is_active) VALUES
  -- legal_staff (9)
  ('呂姿青', 'legal_staff', true),
  ('王悦璇', 'legal_staff', true),   -- 註：CRM 另有 typo 變體「王悅璇」未處理
  ('楊曜綾', 'legal_staff', true),
  ('高琬晴', 'legal_staff', true),
  ('吳笠新', 'legal_staff', true),
  ('陳昕',   'legal_staff', true),
  ('林渙庭', 'legal_staff', true),
  ('湯宜軒', 'legal_staff', true),
  ('于子芹', 'legal_staff', true),
  -- lawyer (23)
  ('林宜嫻', 'lawyer', true),
  ('楊睿杰', 'lawyer', true),
  ('王怡婷', 'lawyer', true),
  ('張家瑜', 'lawyer', true),
  ('楊啓廷', 'lawyer', true),
  ('黃書炫', 'lawyer', true),
  ('陳彥銘', 'lawyer', true),
  ('張文祈', 'lawyer', true),
  ('陳瑋岑', 'lawyer', true),
  ('林品妘', 'lawyer', true),
  ('姜奕成', 'lawyer', true),
  ('莊喬鈞', 'lawyer', true),
  ('楊典翰', 'lawyer', true),
  ('劉庭懿', 'lawyer', true),
  ('李育哲', 'lawyer', true),
  ('王榆心', 'lawyer', true),
  ('謝宗蓉', 'lawyer', true),
  ('秦薇妮', 'lawyer', true),
  ('王相為', 'lawyer', true),
  ('梁馨云', 'lawyer', true),
  ('黃庭汶', 'lawyer', true),
  ('蔡瀞萱', 'lawyer', true),
  ('林敬修', 'lawyer', true);

-- 確認
SELECT name, role, is_active
FROM lawyers
WHERE name IN ('呂姿青','王悦璇','楊曜綾','高琬晴','吳笠新','陳昕','林渙庭','湯宜軒','于子芹',
               '林宜嫻','楊睿杰','王怡婷','張家瑜','楊啓廷','黃書炫','陳彥銘','張文祈','陳瑋岑',
               '林品妘','姜奕成','莊喬鈞','楊典翰','劉庭懿','李育哲','王榆心','謝宗蓉','秦薇妮',
               '王相為','梁馨云','黃庭汶','蔡瀞萱','林敬修')
ORDER BY role, name;
