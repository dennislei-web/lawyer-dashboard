-- v3: 業績算法改用 referral_month/year cols (N/O) 取代 EXTRACT(referral_date)
-- 原因: K 欄 (轉線日期) 在 sheet 內有短格式「M/D」, my Python to_date 認不出來 → NULL.
-- N/O cols 是 010 同仁明確填入的 INT，永遠可靠.
-- Sheet 公式視 K 短格式為今年，效果等同 N/O。

CREATE OR REPLACE FUNCTION rebuild_fact_010_monthly_team(
  p_year_from INT DEFAULT 2021,
  p_year_to   INT DEFAULT 2030
) RETURNS INT AS $$
DECLARE
  affected INT;
BEGIN
  DELETE FROM fact_010_monthly_team WHERE year BETWEEN p_year_from AND p_year_to;

  WITH base AS (
    SELECT
      c.referral_year AS year,
      c.referral_month AS month,
      c.team_owner,
      COUNT(*) AS total_referrals,
      COUNT(*) FILTER (WHERE c.channel IN ('喆律（委前法務）', '喆律（客戶引介）')) AS zhelu_referrals,
      COUNT(*) FILTER (WHERE c.attended = TRUE) AS attended,
      COUNT(*) FILTER (WHERE c.signed = TRUE) AS signed,
      -- 當月業績: first_payment_date 月年 = referral_month/year col
      -- (取代 sheet 公式 MONTH(K)/YEAR(K) — K 有短格式 parse 風險，N/O 可靠)
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
      ), 0) AS current_month_revenue
    FROM raw_010_case c
    WHERE c.referral_year BETWEEN p_year_from AND p_year_to
      AND c.referral_year IS NOT NULL AND c.referral_month IS NOT NULL
      AND c.team_owner IS NOT NULL AND c.team_owner <> ''
    GROUP BY c.referral_year, c.referral_month, c.team_owner
  ),
  cross_first AS (
    -- 分期表 第 1 期 cross-month: first_payment 月年 = target AND referral 月年 ≠ target
    -- 用 referral_month/year col 取代 EXTRACT(referral_date)
    SELECT
      i.team_owner,
      EXTRACT(YEAR FROM i.first_payment_date)::INT AS year,
      EXTRACT(MONTH FROM i.first_payment_date)::INT AS month,
      SUM(i.first_payment_amount) AS amt
    FROM raw_010_installment_case i
    WHERE i.first_payment_date IS NOT NULL
      AND i.team_owner IS NOT NULL AND i.team_owner <> ''
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
    FROM raw_010_installment_case i
    CROSS JOIN LATERAL jsonb_array_elements(i.installment_schedule) AS sched
    WHERE i.installment_schedule IS NOT NULL
      AND i.team_owner IS NOT NULL AND i.team_owner <> ''
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

  WITH base AS (
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
    FROM raw_010_case c
    WHERE c.referral_year BETWEEN p_year_from AND p_year_to
      AND c.referral_year IS NOT NULL AND c.referral_month IS NOT NULL
      AND c.handling_lawyer IS NOT NULL AND c.handling_lawyer <> ''
    GROUP BY c.referral_year, c.referral_month, c.handling_lawyer
  ),
  cross_first AS (
    SELECT
      i.handling_lawyer AS lawyer,
      EXTRACT(YEAR FROM i.first_payment_date)::INT AS year,
      EXTRACT(MONTH FROM i.first_payment_date)::INT AS month,
      SUM(i.first_payment_amount) AS amt
    FROM raw_010_installment_case i
    WHERE i.first_payment_date IS NOT NULL
      AND i.handling_lawyer IS NOT NULL AND i.handling_lawyer <> ''
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
    FROM raw_010_installment_case i
    CROSS JOIN LATERAL jsonb_array_elements(i.installment_schedule) AS sched
    WHERE i.installment_schedule IS NOT NULL
      AND i.handling_lawyer IS NOT NULL AND i.handling_lawyer <> ''
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

COMMENT ON FUNCTION rebuild_fact_010_monthly_team IS 'v3: 業績用 N/O cols 代替 EXTRACT(referral_date) 避開 K 短格式 parse 風險';
COMMENT ON FUNCTION rebuild_fact_010_monthly_lawyer IS 'v3: 同上';
