-- v6: 件數/出席/委任 改為「逐列數、不去重」，複刻總表查詢頁的 COUNTIFS 語意。
--
-- 背景：raw_010_case 的 case_key 含 sheet_row，總表新案插入使既有列位移，
-- 每次 sync 同一案拿到新 sheet_row → 舊列變孤兒累積（實測 81K vs 真實 ~16.7K，~5 層）。
-- v5 的 ROW_NUMBER dedup 原本是用來壓這些累積/區塊重複，但 sync_010.py 已改為
-- 「先清表再重灌」根治累積後，dedup 反而過度合併：把沒出席/沒委任的低資訊列
-- （多欄 NULL、partition key 相同）併掉，導致 2026-05 件數 195 < sheet 223、出席 147 < 173。
--
-- 總表查詢頁的件數其實是純 COUNTIFS：
--   =COUNTIFS('總表'!$I$10000:$I, 律師, '總表'!$N$10000:$N, 月, '總表'!$O$10000:$O, 年)
-- 亦即「逐列數、不去重」，且範圍 I$10000:$I（sheet_row >= 10000）——
-- 因為 <10000 是 2022–2023 舊年份，作者刻意只算 2024+。sheet_row 即試算表真實列號。
--
-- 本版改動（僅 case 端）：
--   • 移除 dedup_case 的 ROW_NUMBER/PARTITION，改為直接 filter。
--   • 加 sheet_row >= 10000，精準對齊 COUNTIFS 範圍。
-- 驗證（2026-05，clean reload 後）：件數 223 / 出席 173 / 委任 59 / 當月收款 2,502,000，
--   林冠宇 20、桃園 16、高雄 5，逐位對齊 sheet。
--
-- installment（分期付款表，跨月收款 dedup_inst）原封不動：它是另一張表、列數 <10000，
--   不適用 sheet_row 切點，且跨月口徑另有疑義，留待後續獨立處理。

CREATE OR REPLACE FUNCTION rebuild_fact_010_monthly_team(
  p_year_from INT DEFAULT 2021,
  p_year_to   INT DEFAULT 2030
) RETURNS INT AS $$
DECLARE
  affected INT;
BEGIN
  DELETE FROM fact_010_monthly_team WHERE year BETWEEN p_year_from AND p_year_to;

  WITH case_rows AS (
    -- 複刻 COUNTIFS：逐列、不去重、僅 sheet_row >= 10000（2024+ 區段）
    SELECT *
    FROM raw_010_case
    WHERE referral_year BETWEEN p_year_from AND p_year_to
      AND referral_year IS NOT NULL AND referral_month IS NOT NULL
      AND team_owner IS NOT NULL AND team_owner <> ''
      AND sheet_row >= 10000
  ),
  dedup_inst AS (
    SELECT *
    FROM (
      SELECT *,
        ROW_NUMBER() OVER (
          PARTITION BY
            COALESCE(handling_lawyer, ''),
            COALESCE(team_owner, ''),
            COALESCE(referral_year::TEXT, ''),
            COALESCE(referral_month::TEXT, ''),
            COALESCE(first_payment_date::TEXT, ''),
            COALESCE(first_payment_amount::TEXT, ''),
            COALESCE(case_amount::TEXT, ''),
            COALESCE(attended::TEXT, ''),
            COALESCE(signed::TEXT, ''),
            COALESCE(channel, '')
          ORDER BY sheet_row
        ) AS rn
      FROM raw_010_installment_case
      WHERE team_owner IS NOT NULL AND team_owner <> ''
    ) t WHERE rn = 1
  ),
  base AS (
    SELECT
      c.referral_year AS year,
      c.referral_month AS month,
      c.team_owner,
      COUNT(*) AS total_referrals,
      COUNT(*) FILTER (WHERE c.channel IN ('喆律（委前法務）', '喆律（客戶引介）')) AS zhelu_referrals,
      COUNT(*) FILTER (WHERE c.attended = TRUE) AS attended,
      COUNT(*) FILTER (WHERE c.signed = TRUE) AS signed,
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
      ), 0) AS current_month_revenue
    FROM case_rows c
    GROUP BY c.referral_year, c.referral_month, c.team_owner
  ),
  cross_first AS (
    SELECT
      i.team_owner,
      EXTRACT(YEAR FROM i.first_payment_date)::INT AS year,
      EXTRACT(MONTH FROM i.first_payment_date)::INT AS month,
      SUM(i.first_payment_amount) AS amt
    FROM dedup_inst i
    WHERE i.first_payment_date IS NOT NULL
      AND i.referral_year IS NOT NULL AND i.referral_month IS NOT NULL
      AND (i.referral_year <> EXTRACT(YEAR FROM i.first_payment_date)::INT
        OR i.referral_month <> EXTRACT(MONTH FROM i.first_payment_date)::INT)
    GROUP BY i.team_owner, EXTRACT(YEAR FROM i.first_payment_date), EXTRACT(MONTH FROM i.first_payment_date)
  ),
  cross_later AS (
    SELECT
      i.team_owner,
      EXTRACT(YEAR FROM (sched->>'date')::DATE)::INT AS year,
      EXTRACT(MONTH FROM (sched->>'date')::DATE)::INT AS month,
      SUM((sched->>'amount')::NUMERIC) AS amt
    FROM dedup_inst i
    CROSS JOIN LATERAL jsonb_array_elements(i.installment_schedule) AS sched
    WHERE i.installment_schedule IS NOT NULL
      AND (sched->>'date') IS NOT NULL AND (sched->>'date') <> ''
      AND (sched->>'amount') IS NOT NULL
    GROUP BY i.team_owner, EXTRACT(YEAR FROM (sched->>'date')::DATE), EXTRACT(MONTH FROM (sched->>'date')::DATE)
  ),
  cross_total AS (
    SELECT team_owner, year, month, COALESCE(SUM(amt), 0) AS cross_revenue
    FROM (SELECT * FROM cross_first UNION ALL SELECT * FROM cross_later) u
    GROUP BY team_owner, year, month
  )
  INSERT INTO fact_010_monthly_team (
    year, month, team_member,
    current_month_revenue, cross_month_revenue, total_revenue,
    total_referrals, zhelu_referrals, o10_referrals,
    attended, attend_rate, signed, sign_rate,
    avg_referral_amount, avg_signed_amount
  )
  SELECT
    b.year, b.month, b.team_owner,
    b.current_month_revenue,
    COALESCE(ct.cross_revenue, 0),
    b.current_month_revenue + COALESCE(ct.cross_revenue, 0),
    b.total_referrals, b.zhelu_referrals, b.total_referrals - b.zhelu_referrals,
    b.attended,
    CASE WHEN b.total_referrals > 0 THEN b.attended::NUMERIC/b.total_referrals ELSE 0 END,
    b.signed,
    CASE WHEN b.attended > 0 THEN b.signed::NUMERIC/b.attended ELSE 0 END,
    CASE WHEN b.total_referrals > 0 THEN b.current_month_revenue / b.total_referrals ELSE 0 END,
    CASE WHEN b.signed > 0 THEN b.current_month_revenue / b.signed ELSE 0 END
  FROM base b
  LEFT JOIN cross_total ct ON ct.team_owner = b.team_owner AND ct.year = b.year AND ct.month = b.month;

  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION rebuild_fact_010_monthly_lawyer(
  p_year_from INT DEFAULT 2021,
  p_year_to   INT DEFAULT 2030
) RETURNS INT AS $$
DECLARE
  affected INT;
BEGIN
  DELETE FROM fact_010_monthly_lawyer WHERE year BETWEEN p_year_from AND p_year_to;

  WITH case_rows AS (
    -- 複刻 COUNTIFS：逐列、不去重、僅 sheet_row >= 10000（2024+ 區段）
    SELECT *
    FROM raw_010_case
    WHERE referral_year BETWEEN p_year_from AND p_year_to
      AND referral_year IS NOT NULL AND referral_month IS NOT NULL
      AND handling_lawyer IS NOT NULL AND handling_lawyer <> ''
      AND sheet_row >= 10000
  ),
  dedup_inst AS (
    SELECT *
    FROM (
      SELECT *,
        ROW_NUMBER() OVER (
          PARTITION BY
            COALESCE(handling_lawyer, ''),
            COALESCE(team_owner, ''),
            COALESCE(referral_year::TEXT, ''),
            COALESCE(referral_month::TEXT, ''),
            COALESCE(first_payment_date::TEXT, ''),
            COALESCE(first_payment_amount::TEXT, ''),
            COALESCE(case_amount::TEXT, ''),
            COALESCE(attended::TEXT, ''),
            COALESCE(signed::TEXT, ''),
            COALESCE(channel, '')
          ORDER BY sheet_row
        ) AS rn
      FROM raw_010_installment_case
      WHERE handling_lawyer IS NOT NULL AND handling_lawyer <> ''
    ) t WHERE rn = 1
  ),
  base AS (
    SELECT
      c.referral_year AS year,
      c.referral_month AS month,
      c.handling_lawyer AS lawyer,
      MAX(c.region) AS region,
      COUNT(*) AS referrals,
      COUNT(*) FILTER (WHERE c.attended = TRUE) AS attended,
      COUNT(*) FILTER (WHERE c.signed = TRUE) AS signed,
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
      ), 0) AS current_month_revenue
    FROM case_rows c
    GROUP BY c.referral_year, c.referral_month, c.handling_lawyer
  ),
  cross_first AS (
    SELECT
      i.handling_lawyer AS lawyer,
      EXTRACT(YEAR FROM i.first_payment_date)::INT AS year,
      EXTRACT(MONTH FROM i.first_payment_date)::INT AS month,
      SUM(i.first_payment_amount) AS amt
    FROM dedup_inst i
    WHERE i.first_payment_date IS NOT NULL
      AND i.referral_year IS NOT NULL AND i.referral_month IS NOT NULL
      AND (i.referral_year <> EXTRACT(YEAR FROM i.first_payment_date)::INT
        OR i.referral_month <> EXTRACT(MONTH FROM i.first_payment_date)::INT)
    GROUP BY i.handling_lawyer, EXTRACT(YEAR FROM i.first_payment_date), EXTRACT(MONTH FROM i.first_payment_date)
  ),
  cross_later AS (
    SELECT
      i.handling_lawyer AS lawyer,
      EXTRACT(YEAR FROM (sched->>'date')::DATE)::INT AS year,
      EXTRACT(MONTH FROM (sched->>'date')::DATE)::INT AS month,
      SUM((sched->>'amount')::NUMERIC) AS amt
    FROM dedup_inst i
    CROSS JOIN LATERAL jsonb_array_elements(i.installment_schedule) AS sched
    WHERE i.installment_schedule IS NOT NULL
      AND (sched->>'date') IS NOT NULL AND (sched->>'date') <> ''
      AND (sched->>'amount') IS NOT NULL
    GROUP BY i.handling_lawyer, EXTRACT(YEAR FROM (sched->>'date')::DATE), EXTRACT(MONTH FROM (sched->>'date')::DATE)
  ),
  cross_total AS (
    SELECT lawyer, year, month, COALESCE(SUM(amt), 0) AS cross_revenue
    FROM (SELECT * FROM cross_first UNION ALL SELECT * FROM cross_later) u
    GROUP BY lawyer, year, month
  ),
  enriched AS (
    SELECT
      b.year, b.month, b.lawyer, b.region, b.referrals, b.attended, b.signed,
      b.current_month_revenue,
      COALESCE(ct.cross_revenue, 0) AS cross_month_revenue,
      b.current_month_revenue + COALESCE(ct.cross_revenue, 0) AS total_revenue,
      t.monthly_target, t.weekly_target
    FROM base b
    LEFT JOIN cross_total ct ON ct.lawyer = b.lawyer AND ct.year = b.year AND ct.month = b.month
    LEFT JOIN raw_010_lawyer_target t ON t.lawyer = b.lawyer AND t.year = b.year AND t.month = b.month
  )
  INSERT INTO fact_010_monthly_lawyer (
    year, month, lawyer, region,
    referrals, weekly_target, monthly_target,
    attended, attend_rate, signed, sign_rate,
    current_month_revenue, cross_month_revenue, total_revenue,
    avg_referral_amount, avg_signed_amount,
    overall_sign_rate, avg_unit_price_wan, referral_status
  )
  SELECT
    year, month, lawyer, region,
    referrals, weekly_target, monthly_target,
    attended,
    CASE WHEN referrals > 0 THEN attended::NUMERIC/referrals ELSE 0 END,
    signed,
    CASE WHEN attended > 0 THEN signed::NUMERIC/attended ELSE 0 END,
    current_month_revenue, cross_month_revenue, total_revenue,
    CASE WHEN referrals > 0 THEN current_month_revenue/referrals ELSE 0 END,
    CASE WHEN signed > 0 THEN current_month_revenue/signed ELSE 0 END,
    CASE WHEN referrals > 0 AND attended > 0
      THEN (attended::NUMERIC/referrals) * (signed::NUMERIC/attended)
      ELSE 0 END,
    CASE WHEN referrals > 0 THEN total_revenue / referrals / 10000.0 ELSE 0 END,
    CASE
      WHEN referrals = 0 THEN '-'
      WHEN (CASE WHEN referrals > 0 AND attended > 0 THEN (attended::NUMERIC/referrals)*(signed::NUMERIC/attended) ELSE 0 END) > 0.35
        AND (CASE WHEN referrals > 0 THEN total_revenue/referrals/10000.0 ELSE 0 END) > 3
        THEN '優先'
      WHEN (CASE WHEN referrals > 0 AND attended > 0 THEN (attended::NUMERIC/referrals)*(signed::NUMERIC/attended) ELSE 0 END) >= 0.28
        OR (CASE WHEN referrals > 0 THEN total_revenue/referrals/10000.0 ELSE 0 END) >= 2.3
        THEN '正常'
      ELSE '暫緩'
    END
  FROM enriched;

  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_fact_010_monthly_team IS 'v6: 件數逐列數不去重 + sheet_row>=10000，複刻 COUNTIFS（搭配 sync 先清表再重灌）';
COMMENT ON FUNCTION rebuild_fact_010_monthly_lawyer IS 'v6: 同上';
