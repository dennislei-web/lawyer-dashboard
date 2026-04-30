-- Reassign 杜柏賢/游政恩 的諮詢案給 李杰峰，合併進 monthly_stats
-- 在 Supabase SQL Editor 執行；BEGIN/COMMIT 包住，確認後再 commit
--
-- 對象：
--   杜柏賢 (ef7427db-...) — 1 筆 2022-11 $1,500 unsigned
--   游政恩 (0be01b70-...) — 1 筆 2026-01 $70,000 signed
-- 接收者：
--   李杰峰 (9072cdcd-...) — role=lawyer, 桃園
--
-- 註：張飛宇 / 股東 / 客戶關係部 / 蘇思蓓 / 6 位法務 在 consultation_cases
-- 與 monthly_stats 都是 0 筆，不需要 SQL 操作（已從 LAWYER_DEPARTMENTS 排除）。

BEGIN;

-- Step 1: 預覽要 reassign 的 consultation_cases
SELECT case_date, case_number, client_name, revenue, collected, is_signed,
       (SELECT name FROM lawyers WHERE id = c.lawyer_id) AS old_lawyer
FROM consultation_cases c
WHERE lawyer_id IN (
  'ef7427db-948a-4101-ae68-d48b5314bb59',  -- 杜柏賢
  '0be01b70-20df-4510-9e30-54af290feb15'   -- 游政恩
);

-- Step 2: 重新指派 consultation_cases 給 李杰峰
UPDATE consultation_cases
SET lawyer_id  = '9072cdcd-87ac-4e85-840a-6b8b64292a15',  -- 李杰峰
    updated_at = NOW()
WHERE lawyer_id IN (
  'ef7427db-948a-4101-ae68-d48b5314bb59',
  '0be01b70-20df-4510-9e30-54af290feb15'
);

-- Step 3: 合併進 李杰峰 既有的 monthly_stats
-- 2022-11: +1 諮詢, +0 簽, +1500 營收
UPDATE monthly_stats
SET consult_count = consult_count + 1,
    revenue       = revenue + 1500,
    collected     = collected + 1500,
    sign_rate     = ROUND(signed_count::numeric / (consult_count + 1) * 100, 2),
    updated_at    = NOW()
WHERE lawyer_id = '9072cdcd-87ac-4e85-840a-6b8b64292a15' AND month = '2022-11';

-- 2026-01: +1 諮詢, +1 簽, +70000 營收
UPDATE monthly_stats
SET consult_count = consult_count + 1,
    signed_count  = signed_count + 1,
    revenue       = revenue + 70000,
    collected     = collected + 70000,
    sign_rate     = ROUND((signed_count + 1)::numeric / (consult_count + 1) * 100, 2),
    updated_at    = NOW()
WHERE lawyer_id = '9072cdcd-87ac-4e85-840a-6b8b64292a15' AND month = '2026-01';

-- Step 4: 刪除原本掛在 杜柏賢/游政恩 的 monthly_stats 紀錄
DELETE FROM monthly_stats
WHERE lawyer_id IN (
  'ef7427db-948a-4101-ae68-d48b5314bb59',
  '0be01b70-20df-4510-9e30-54af290feb15'
);

-- Step 5: 驗證合併結果
SELECT lawyer_id, month, consult_count, signed_count, sign_rate, revenue, collected
FROM monthly_stats
WHERE lawyer_id = '9072cdcd-87ac-4e85-840a-6b8b64292a15'
  AND month IN ('2022-11', '2026-01');

COMMIT;
