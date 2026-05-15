-- 法律010 ETL schema
-- Mirror 法律010總表 (Google Sheet) → 兩個 raw 表 + 兩個重算 fact 表
-- 算法來源: reference_010_sheet3_algorithm.md

-- ============================================================
-- raw_010_case：mirror 「總表」[10] 案件主檔
-- ============================================================
-- PII 欄位（當事人姓名/電話/身分證）不存，只存 case_key hash 做 dedupe
CREATE TABLE IF NOT EXISTS raw_010_case (
  case_key         TEXT PRIMARY KEY,           -- hash(client_name + intake_date + lawyer)
  sheet_row        INT,                         -- 來源 row index 給 traceability
  team_owner       TEXT,                        -- col A  010 窗口
  channel          TEXT,                        -- col B  進線管道
  region           TEXT,                        -- col C  地區
  case_type        TEXT,                        -- col F  案件類型
  case_reason      TEXT,                        -- col G  案由
  handling_lawyer  TEXT,                        -- col I  接案律師
  intake_date      DATE,                        -- col J  進線日期
  referral_date    DATE,                        -- col K  轉線日期
  follow_up_date   DATE,                        -- col L
  is_urgent        TEXT,                        -- col M
  referral_month   INT,                         -- col N
  referral_year    INT,                         -- col O
  attended         BOOLEAN,                     -- col Q  是否出席 (是/否)
  not_attended_reason TEXT,                     -- col R
  meeting_date     DATE,                        -- col S
  signed           BOOLEAN,                     -- col U  委任與否
  case_amount      NUMERIC,                     -- col V  案件委任金額
  first_payment_amount NUMERIC,                 -- col W  第一次收款金額 ⭐ sheet[3] 業績用此欄
  first_payment_date DATE,                      -- col X
  installment_count INT,                        -- col Z  分期期數
  unpaid_amount    NUMERIC,                     -- col AA
  -- col AB-AW 第二期~第十二期 (date,amount) 11 pairs → JSON
  installment_schedule JSONB,
  is_cross_month   TEXT,                        -- col AY
  payment_month    INT,                         -- col BB
  payment_year     INT,                         -- col BC
  synced_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_010_case_team_owner ON raw_010_case (team_owner, referral_year, referral_month);
CREATE INDEX IF NOT EXISTS idx_raw_010_case_lawyer ON raw_010_case (handling_lawyer, referral_year, referral_month);
CREATE INDEX IF NOT EXISTS idx_raw_010_case_dates ON raw_010_case (referral_date, first_payment_date);

-- ============================================================
-- raw_010_installment_case：mirror 「分期付款案件表」[4]
-- ============================================================
-- schema 跟 raw_010_case 大致相同，但 col offset +1（前面有 spacer col A）
CREATE TABLE IF NOT EXISTS raw_010_installment_case (
  case_key         TEXT PRIMARY KEY,
  sheet_row        INT,
  team_owner       TEXT,                        -- col B
  channel          TEXT,                        -- col C
  region           TEXT,                        -- col D
  case_type        TEXT,                        -- col G
  case_reason      TEXT,                        -- col H
  handling_lawyer  TEXT,                        -- col J
  intake_date      DATE,                        -- col K
  referral_date    DATE,                        -- col L
  follow_up_date   DATE,                        -- col M
  referral_month   INT,                         -- col O
  referral_year    INT,                         -- col P
  attended         BOOLEAN,                     -- col R
  signed           BOOLEAN,                     -- col V
  case_amount      NUMERIC,                     -- col W
  first_payment_amount NUMERIC,                 -- col X
  first_payment_date DATE,                      -- col Y
  installment_count INT,                        -- col AA
  unpaid_amount    NUMERIC,                     -- col AB
  installment_schedule JSONB,                   -- col AC-AX (date,amount) pairs
  synced_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_010_inst_team_owner ON raw_010_installment_case (team_owner);
CREATE INDEX IF NOT EXISTS idx_raw_010_inst_lawyer ON raw_010_installment_case (handling_lawyer);

-- ============================================================
-- raw_010_lawyer_target：mirror「每週/月轉介律師目標案件數」[9]
-- ============================================================
-- 每月每律師一列
CREATE TABLE IF NOT EXISTS raw_010_lawyer_target (
  year             INT,
  month            INT,
  lawyer           TEXT,
  monthly_target   INT,
  weekly_target    INT,
  region           TEXT,
  synced_at        TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (year, month, lawyer)
);

-- ============================================================
-- fact_010_monthly_team：010 同仁 月度聚合（sheet [3] top block）
-- ============================================================
CREATE TABLE IF NOT EXISTS fact_010_monthly_team (
  year                  INT,
  month                 INT,
  team_member           TEXT,
  current_month_revenue NUMERIC,        -- F: 當月業績
  cross_month_revenue   NUMERIC,        -- G: 跨月業績
  total_revenue         NUMERIC,        -- H = F + G
  total_referrals       INT,            -- J: 總轉出件數
  zhelu_referrals       INT,            -- L: 喆律流量
  o10_referrals         INT,            -- K = J - L
  attended              INT,            -- M
  attend_rate           NUMERIC,        -- N = M/J
  signed                INT,            -- O
  sign_rate             NUMERIC,        -- P = O/M
  avg_referral_amount   NUMERIC,        -- Q = F/J
  avg_signed_amount     NUMERIC,        -- R = F/O
  computed_at           TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (year, month, team_member)
);

-- ============================================================
-- fact_010_monthly_lawyer：合作律師 月度聚合（sheet [3] bottom block）
-- ============================================================
CREATE TABLE IF NOT EXISTS fact_010_monthly_lawyer (
  year                  INT,
  month                 INT,
  lawyer                TEXT,
  region                TEXT,
  referrals             INT,            -- C: 已轉案件數
  weekly_target         INT,            -- D
  monthly_target        INT,            -- (sheet 沒這 col 在此 block，從 target 表 lookup)
  attended              INT,            -- F
  attend_rate           NUMERIC,        -- G = F/C
  signed                INT,            -- H
  sign_rate             NUMERIC,        -- I = H/F
  current_month_revenue NUMERIC,        -- J: 收款金額（當月）
  cross_month_revenue   NUMERIC,        -- M: 跨月收款金額
  total_revenue         NUMERIC,        -- N = J + M
  avg_referral_amount   NUMERIC,        -- K = J/C
  avg_signed_amount     NUMERIC,        -- L = J/H
  overall_sign_rate     NUMERIC,        -- T = G * I (出席率 × 委任率)
  avg_unit_price_wan    NUMERIC,        -- U = N/C/10000  ⭐ BI 警示
  referral_status       TEXT,           -- V: 優先/正常/暫緩/-
  computed_at           TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (year, month, lawyer)
);

CREATE INDEX IF NOT EXISTS idx_fact_team_period ON fact_010_monthly_team (year DESC, month DESC);
CREATE INDEX IF NOT EXISTS idx_fact_lawyer_period ON fact_010_monthly_lawyer (year DESC, month DESC);
CREATE INDEX IF NOT EXISTS idx_fact_lawyer_status ON fact_010_monthly_lawyer (referral_status, year DESC, month DESC);

-- ============================================================
-- RPC: rebuild fact tables from raw (for given year/month range)
-- ============================================================
-- 一次 build 全部歷史月份；也可帶 args 限縮範圍

CREATE OR REPLACE FUNCTION rebuild_fact_010_monthly_team(
  p_year_from INT DEFAULT 2021,
  p_year_to   INT DEFAULT 2030
) RETURNS INT AS $$
DECLARE
  affected INT;
BEGIN
  -- 清掉範圍內
  DELETE FROM fact_010_monthly_team
   WHERE year BETWEEN p_year_from AND p_year_to;

  -- 重算
  -- Q1=A: 件數用 referral_month/year (N/O cols)，業績用 referral_date (K) AND first_payment_date (X) 月年
  INSERT INTO fact_010_monthly_team (
    year, month, team_member,
    current_month_revenue, cross_month_revenue, total_revenue,
    total_referrals, zhelu_referrals, o10_referrals,
    attended, attend_rate, signed, sign_rate,
    avg_referral_amount, avg_signed_amount
  )
  SELECT
    c.referral_year AS year,
    c.referral_month AS month,
    c.team_owner AS team_member,
    -- F: 當月業績 = SUM(first_payment_amount)
    -- WHERE first_payment_date 月年 = group AND referral_date 月年 = group
    COALESCE(SUM(c.first_payment_amount) FILTER (
      WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
        AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
        AND EXTRACT(MONTH FROM c.referral_date) = c.referral_month
        AND EXTRACT(YEAR FROM c.referral_date) = c.referral_year
    ), 0) AS current_month_revenue,
    -- G: 跨月業績 — TODO v2: 從 raw_010_installment_case 加總
    0 AS cross_month_revenue,
    COALESCE(SUM(c.first_payment_amount) FILTER (
      WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
        AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
        AND EXTRACT(MONTH FROM c.referral_date) = c.referral_month
        AND EXTRACT(YEAR FROM c.referral_date) = c.referral_year
    ), 0) AS total_revenue,
    COUNT(*) AS total_referrals,
    COUNT(*) FILTER (WHERE c.channel IN ('喆律（委前法務）', '喆律（客戶引介）')) AS zhelu_referrals,
    COUNT(*) - COUNT(*) FILTER (WHERE c.channel IN ('喆律（委前法務）', '喆律（客戶引介）')) AS o10_referrals,
    COUNT(*) FILTER (WHERE c.attended = TRUE) AS attended,
    CASE WHEN COUNT(*) > 0 THEN
      COUNT(*) FILTER (WHERE c.attended = TRUE)::NUMERIC / COUNT(*)
    ELSE 0 END AS attend_rate,
    COUNT(*) FILTER (WHERE c.signed = TRUE) AS signed,
    CASE WHEN COUNT(*) FILTER (WHERE c.attended = TRUE) > 0 THEN
      COUNT(*) FILTER (WHERE c.signed = TRUE)::NUMERIC / COUNT(*) FILTER (WHERE c.attended = TRUE)
    ELSE 0 END AS sign_rate,
    -- Q: 轉介均價 = F/J  (F 用上面那個 filter, J 是 COUNT(*))
    CASE WHEN COUNT(*) > 0 THEN
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
          AND EXTRACT(MONTH FROM c.referral_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.referral_date) = c.referral_year
      ), 0)::NUMERIC / COUNT(*)
    ELSE 0 END AS avg_referral_amount,
    -- R: 委任均價 = F/O (F 同上, O = signed count)
    CASE WHEN COUNT(*) FILTER (WHERE c.signed = TRUE) > 0 THEN
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
          AND EXTRACT(MONTH FROM c.referral_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.referral_date) = c.referral_year
      ), 0)::NUMERIC / COUNT(*) FILTER (WHERE c.signed = TRUE)
    ELSE 0 END AS avg_signed_amount
  FROM raw_010_case c
  WHERE c.referral_year BETWEEN p_year_from AND p_year_to
    AND c.referral_year IS NOT NULL
    AND c.referral_month IS NOT NULL
    AND c.team_owner IS NOT NULL
    AND c.team_owner <> ''
  GROUP BY c.referral_year, c.referral_month, c.team_owner;

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
  DELETE FROM fact_010_monthly_lawyer
   WHERE year BETWEEN p_year_from AND p_year_to;

  WITH base AS (
    SELECT
      c.referral_year AS year,
      c.referral_month AS month,
      c.handling_lawyer AS lawyer,
      MAX(c.region) AS region,
      COUNT(*) AS referrals,
      COUNT(*) FILTER (WHERE c.attended = TRUE) AS attended,
      COUNT(*) FILTER (WHERE c.signed = TRUE) AS signed,
      -- Q1=A: 當月業績 J:
      -- WHERE first_payment_date 月年 = group AND referral_date 月年 = group
      COALESCE(SUM(c.first_payment_amount) FILTER (
        WHERE EXTRACT(MONTH FROM c.first_payment_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.first_payment_date) = c.referral_year
          AND EXTRACT(MONTH FROM c.referral_date) = c.referral_month
          AND EXTRACT(YEAR FROM c.referral_date) = c.referral_year
      ), 0) AS current_month_revenue
    FROM raw_010_case c
    WHERE c.referral_year BETWEEN p_year_from AND p_year_to
      AND c.referral_year IS NOT NULL
      AND c.referral_month IS NOT NULL
      AND c.handling_lawyer IS NOT NULL
      AND c.handling_lawyer <> ''
    GROUP BY c.referral_year, c.referral_month, c.handling_lawyer
  ),
  with_target AS (
    SELECT
      b.*,
      t.monthly_target,
      t.weekly_target
    FROM base b
    LEFT JOIN raw_010_lawyer_target t
      ON t.year = b.year AND t.month = b.month AND t.lawyer = b.lawyer
  )
  INSERT INTO fact_010_monthly_lawyer (
    year, month, lawyer, region,
    referrals, weekly_target, monthly_target,
    attended, attend_rate,
    signed, sign_rate,
    current_month_revenue, cross_month_revenue, total_revenue,
    avg_referral_amount, avg_signed_amount,
    overall_sign_rate, avg_unit_price_wan, referral_status
  )
  SELECT
    year, month, lawyer, region,
    referrals, weekly_target, monthly_target,
    attended,
    CASE WHEN referrals > 0 THEN attended::NUMERIC/referrals ELSE 0 END AS attend_rate,
    signed,
    CASE WHEN attended > 0 THEN signed::NUMERIC/attended ELSE 0 END AS sign_rate,
    current_month_revenue,
    0 AS cross_month_revenue,  -- TODO v2: join installment
    current_month_revenue AS total_revenue,
    CASE WHEN referrals > 0 THEN current_month_revenue/referrals ELSE 0 END,
    CASE WHEN signed > 0 THEN current_month_revenue/signed ELSE 0 END,
    -- T = 出席率 × 委任率
    CASE
      WHEN referrals > 0 AND attended > 0
      THEN (attended::NUMERIC/referrals) * (signed::NUMERIC/attended)
      ELSE 0
    END AS overall_sign_rate,
    -- U = total_revenue / 件數 / 10000
    CASE WHEN referrals > 0 THEN current_month_revenue / referrals / 10000.0 ELSE 0 END AS avg_unit_price_wan,
    -- V 轉案狀態
    CASE
      WHEN referrals = 0 THEN '-'
      WHEN (CASE WHEN referrals > 0 AND attended > 0 THEN (attended::NUMERIC/referrals) * (signed::NUMERIC/attended) ELSE 0 END) > 0.35
        AND (CASE WHEN referrals > 0 THEN current_month_revenue / referrals / 10000.0 ELSE 0 END) > 3
        THEN '優先'
      WHEN (CASE WHEN referrals > 0 AND attended > 0 THEN (attended::NUMERIC/referrals) * (signed::NUMERIC/attended) ELSE 0 END) >= 0.28
        OR (CASE WHEN referrals > 0 THEN current_month_revenue / referrals / 10000.0 ELSE 0 END) >= 2.3
        THEN '正常'
      ELSE '暫緩'
    END AS referral_status
  FROM with_target;

  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE raw_010_case IS '法律010總表「總表」鏡像；PII 欄不存';
COMMENT ON TABLE raw_010_installment_case IS '法律010總表「分期付款案件表」鏡像';
COMMENT ON TABLE raw_010_lawyer_target IS '法律010總表「每週/月轉介律師目標案件數」鏡像';
COMMENT ON TABLE fact_010_monthly_team IS '010 同仁月度聚合（重建 sheet[3] top block）';
COMMENT ON TABLE fact_010_monthly_lawyer IS '合作律師月度聚合（重建 sheet[3] bottom block）';
COMMENT ON FUNCTION rebuild_fact_010_monthly_team IS '從 raw 重算 team fact；TODO: 加入分期跨月';
COMMENT ON FUNCTION rebuild_fact_010_monthly_lawyer IS '從 raw 重算 lawyer fact；TODO: 加入分期跨月、轉案狀態用 total_revenue 而非 current_month';
