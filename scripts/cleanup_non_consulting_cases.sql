-- 清除非諮詢律師的諮詢紀錄
-- 對象：張飛宇=財務主管 / 股東 / 客戶關係部 / 蘇思蓓 / 杜柏賢 / 游政恩
-- 在 Supabase SQL Editor 執行；先看 SELECT 結果再 COMMIT

BEGIN;

-- Step 1: 預覽 consultation_cases
SELECT lawyer_id, case_date, case_number, client_name, revenue, is_signed,
       (SELECT name FROM lawyers WHERE id = c.lawyer_id) AS lawyer_name
FROM consultation_cases c
WHERE lawyer_id IN (
  '76636726-2f80-4888-895f-ccbaf7c2ba81',  -- 張飛宇 (財務主管)
  '27ea064c-98eb-477e-8c61-13b052ab23ed',  -- 股東
  '7794fbee-c262-4a66-acba-11b712833165',  -- 客戶關係部
  'ff69ecc5-224b-4ce8-8a6e-618721927479',  -- 蘇思蓓
  'ef7427db-948a-4101-ae68-d48b5314bb59',  -- 杜柏賢
  '0be01b70-20df-4510-9e30-54af290feb15'   -- 游政恩
);

-- Step 2: 預覽 monthly_stats
SELECT lawyer_id, month, consult_count, signed_count, revenue, collected,
       (SELECT name FROM lawyers WHERE id = m.lawyer_id) AS lawyer_name
FROM monthly_stats m
WHERE lawyer_id IN (
  '76636726-2f80-4888-895f-ccbaf7c2ba81',
  '27ea064c-98eb-477e-8c61-13b052ab23ed',
  '7794fbee-c262-4a66-acba-11b712833165',
  'ff69ecc5-224b-4ce8-8a6e-618721927479',
  'ef7427db-948a-4101-ae68-d48b5314bb59',
  '0be01b70-20df-4510-9e30-54af290feb15'
);

-- Step 3: 實際刪除
DELETE FROM consultation_cases
WHERE lawyer_id IN (
  '76636726-2f80-4888-895f-ccbaf7c2ba81',
  '27ea064c-98eb-477e-8c61-13b052ab23ed',
  '7794fbee-c262-4a66-acba-11b712833165',
  'ff69ecc5-224b-4ce8-8a6e-618721927479',
  'ef7427db-948a-4101-ae68-d48b5314bb59',
  '0be01b70-20df-4510-9e30-54af290feb15'
);

DELETE FROM monthly_stats
WHERE lawyer_id IN (
  '76636726-2f80-4888-895f-ccbaf7c2ba81',
  '27ea064c-98eb-477e-8c61-13b052ab23ed',
  '7794fbee-c262-4a66-acba-11b712833165',
  'ff69ecc5-224b-4ce8-8a6e-618721927479',
  'ef7427db-948a-4101-ae68-d48b5314bb59',
  '0be01b70-20df-4510-9e30-54af290feb15'
);

COMMIT;
