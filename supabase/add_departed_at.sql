-- 1. 加 departed_at 欄位
ALTER TABLE lawyers ADD COLUMN IF NOT EXISTS departed_at DATE;

-- 2. 修正 5 位被誤關 is_active 的在職同仁
UPDATE lawyers SET is_active = true, departed_at = NULL
WHERE name IN ('林俐妤','林雨辰','楊喬伊','蔡宛陵','郭玟樺')
  AND is_active = false;

-- 3. 回填 20 位已離職者的離職日（依薪資紀錄最後一個月之月底）
UPDATE lawyers SET departed_at = '2023-03-31' WHERE name = '丁巧欣' AND is_active = false;
UPDATE lawyers SET departed_at = '2025-05-31' WHERE name = '劉羽芯' AND is_active = false;
UPDATE lawyers SET departed_at = '2026-04-30' WHERE name = '唐于淇' AND is_active = false;
UPDATE lawyers SET departed_at = '2024-02-29' WHERE name = '張紹成' AND is_active = false;
UPDATE lawyers SET departed_at = '2024-08-31' WHERE name = '徐佳緯' AND is_active = false;
UPDATE lawyers SET departed_at = '2023-04-30' WHERE name = '李仁傑' AND is_active = false;
UPDATE lawyers SET departed_at = '2025-12-31' WHERE name = '杜柏賢' AND is_active = false;
UPDATE lawyers SET departed_at = '2023-03-31' WHERE name = '林貝珍' AND is_active = false;
UPDATE lawyers SET departed_at = '2024-09-30' WHERE name = '楊于瑾' AND is_active = false;
UPDATE lawyers SET departed_at = '2022-04-30' WHERE name = '楊筑鈞' AND is_active = false;
UPDATE lawyers SET departed_at = '2023-07-31' WHERE name = '紀宜君' AND is_active = false;
UPDATE lawyers SET departed_at = '2025-09-30' WHERE name = '紀淑卿' AND is_active = false;
UPDATE lawyers SET departed_at = '2023-04-30' WHERE name = '莊清翊' AND is_active = false;
UPDATE lawyers SET departed_at = '2025-10-31' WHERE name = '蔡愷凌' AND is_active = false;
UPDATE lawyers SET departed_at = '2024-12-31' WHERE name = '蕭予馨' AND is_active = false;
UPDATE lawyers SET departed_at = '2023-08-31' WHERE name = '陳宛婷' AND is_active = false;
UPDATE lawyers SET departed_at = '2022-09-30' WHERE name = '陳沛羲' AND is_active = false;
UPDATE lawyers SET departed_at = '2026-03-31' WHERE name = '黃惠群' AND is_active = false;
UPDATE lawyers SET departed_at = '2024-04-30' WHERE name = '黃裕恆' AND is_active = false;
UPDATE lawyers SET departed_at = '2025-06-30' WHERE name = '黃鈺婷' AND is_active = false;

-- 游政恩 無薪資紀錄，departed_at 保留 NULL（dashboard 視為「不明日期但已離職」）

-- 4. 確認結果
SELECT name, role, is_active, departed_at
FROM lawyers
WHERE is_active = false OR name IN ('林俐妤','林雨辰','楊喬伊','蔡宛陵','郭玟樺')
ORDER BY is_active DESC, departed_at NULLS LAST, name;
