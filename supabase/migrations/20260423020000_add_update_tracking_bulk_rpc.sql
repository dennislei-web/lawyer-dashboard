-- Bulk update tracking fields on consultation_cases in a single RPC call.
-- 原本 daily_update.py 逐筆 PATCH 1698 次 × ~200ms ≈ 6–10 分鐘。
-- 改用此 RPC 一次送一個 jsonb array，讓 PostgreSQL 批次 UPDATE，< 5 秒完成。

CREATE OR REPLACE FUNCTION public.update_tracking_bulk(data jsonb)
RETURNS int
LANGUAGE sql
AS $$
  WITH upd AS (
    UPDATE public.consultation_cases c
    SET tracking_staff  = i.tracking_staff,
        tracking_notes  = i.tracking_notes,
        tracking_status = i.tracking_status
    FROM jsonb_to_recordset(data) AS i(
      case_number     text,
      tracking_staff  text,
      tracking_notes  text,
      tracking_status text
    )
    WHERE c.case_number = i.case_number
    RETURNING c.id
  )
  SELECT count(*)::int FROM upd;
$$;

COMMENT ON FUNCTION public.update_tracking_bulk(jsonb) IS
  '批次更新 consultation_cases 的 tracking_staff / tracking_notes / tracking_status，由 scripts/daily_update.py Step 3 呼叫';
