-- 補進 32 位「lawyers 表查無但 CRM 案件出現過 + 已離職」的人
-- 來源：scan_ranking_lurkers.py，依 finance_employees_monthly 末薪推估離職末日
-- 張瓊翔 無 finance 紀錄，departed_at 留 NULL（dashboard 視為「永遠已離職」）

INSERT INTO lawyers (name, role, is_active, departed_at) VALUES
  ('吳其昀', 'lawyer', false, '2025-04-30'),
  ('鍾宇',   'lawyer', false, '2025-11-30'),
  ('鄧采其', 'lawyer', false, '2025-06-30'),
  ('張璦翔', 'lawyer', false, '2024-10-31'),
  ('邱昱瑋', 'lawyer', false, '2024-07-31'),
  ('許峻瑋', 'lawyer', false, '2025-05-31'),
  ('謝佳純', 'lawyer', false, '2023-05-31'),
  ('劉育杰', 'lawyer', false, '2024-10-31'),
  ('詹佳欣', 'lawyer', false, '2023-07-31'),
  ('陳昱靜', 'lawyer', false, '2025-04-30'),
  ('王郁允', 'lawyer', false, '2025-06-30'),
  ('劉曉穎', 'lawyer', false, '2023-08-31'),
  ('韓智宇', 'lawyer', false, '2024-04-30'),
  ('蔡政軒', 'lawyer', false, '2025-09-30'),
  ('簡子澐', 'lawyer', false, '2024-09-30'),
  ('陳彥妏', 'lawyer', false, '2023-07-31'),
  ('石宗豪', 'lawyer', false, '2023-10-31'),
  ('朱玉珍', 'lawyer', false, '2022-12-31'),
  ('張芸榕', 'lawyer', false, '2023-03-31'),
  ('梁琳',   'lawyer', false, '2024-04-30'),
  ('李汸純', 'lawyer', false, '2025-06-30'),
  ('鄭家豐', 'lawyer', false, '2025-03-31'),
  ('賴可欣', 'lawyer', false, '2024-05-31'),
  ('陳思瑄', 'lawyer', false, '2023-09-30'),
  ('潘建儒', 'lawyer', false, '2023-07-31'),
  ('林緯翰', 'lawyer', false, '2024-02-29'),
  ('林書緯', 'lawyer', false, '2024-06-30'),
  ('葉宜綸', 'lawyer', false, '2024-08-31'),
  ('林衫珊', 'lawyer', false, '2023-10-31'),
  ('張詠晴', 'lawyer', false, '2022-07-31'),
  ('柳淑萍', 'lawyer', false, '2022-04-30'),
  ('張瓊翔', 'lawyer', false, NULL);

-- 確認
SELECT name, departed_at, is_active
FROM lawyers
WHERE name IN ('吳其昀','鍾宇','鄧采其','張璦翔','邱昱瑋','許峻瑋','謝佳純','劉育杰','詹佳欣',
               '陳昱靜','王郁允','劉曉穎','韓智宇','蔡政軒','簡子澐','陳彥妏','石宗豪','朱玉珍',
               '張芸榕','梁琳','李汸純','鄭家豐','賴可欣','陳思瑄','潘建儒','林緯翰','林書緯',
               '葉宜綸','林衫珊','張詠晴','柳淑萍','張瓊翔')
ORDER BY departed_at NULLS LAST, name;
