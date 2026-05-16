-- 法顧 reconcile 撈 revenue_records 推到 server side
--
-- 原本前端是：撈 advisor_cases → 全撈 revenue_records 3 年份（序列分頁 1000 筆/次）
-- → client-side filter 比對 client_name + 「（前名稱：xxx）」alias 變體。
-- 資料量越大 round-trip 越多，整頁卡在「載入中…」。
--
-- 改成單一 RPC：advisor 客戶名單 + alias normalize 都在 PG 內完成，
-- 只回傳真正命中的 records，1 個 round-trip 結束。
--
-- normalize 規則跟前端 normalizeClientName() 對齊：
--   去掉「（前名稱：xxx）」/「(前名稱:xxx)」（全形半形括號 + 全形半形冒號），再 trim。

CREATE OR REPLACE FUNCTION get_advisor_reconcile_records(
  p_start_date date,
  p_end_date   date
)
RETURNS TABLE (
  record_date      date,
  amount           numeric,
  transaction_type text,
  client_name      text,
  group_name       text
)
LANGUAGE sql
STABLE
SECURITY INVOKER
AS $$
  WITH advisor_names AS (
    SELECT DISTINCT name FROM (
      SELECT client_name AS name FROM advisor_cases
      WHERE client_name IS NOT NULL AND client_name <> ''
      UNION
      SELECT btrim(regexp_replace(client_name, '[（(]前名稱[：:][^）)]*[）)]', '', 'g'))
      FROM advisor_cases
      WHERE client_name IS NOT NULL AND client_name <> ''
    ) t
    WHERE name IS NOT NULL AND name <> ''
  )
  SELECT
    r.record_date,
    r.amount,
    r.transaction_type,
    r.client_name,
    r.group_name
  FROM revenue_records r
  WHERE r.is_void = false
    AND r.client_name IS NOT NULL
    AND r.record_date >= p_start_date
    AND r.record_date <= p_end_date
    AND (
      r.client_name IN (SELECT name FROM advisor_names)
      OR btrim(regexp_replace(r.client_name, '[（(]前名稱[：:][^）)]*[）)]', '', 'g'))
         IN (SELECT name FROM advisor_names)
    );
$$;

GRANT EXECUTE ON FUNCTION get_advisor_reconcile_records(date, date) TO authenticated;
