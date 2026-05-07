-- ============================================================
--  OKR 追蹤儀表板 - Schema
--  目標：把喆律 2026 年的 OKR 各項 KR 目標、手動實績、里程碑存進 DB
--  前置條件：lawyers 表已存在、is_admin() 函數已存在、update_updated_at_column() 已存在
-- ============================================================

-- 1. OKR 目標：每年 × 每 KR × 每月（month NULL 代表年度目標）
CREATE TABLE IF NOT EXISTS okr_targets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year          INTEGER NOT NULL,
    kr_code       TEXT NOT NULL,
    month         INTEGER CHECK (month IS NULL OR month BETWEEN 1 AND 12),
    target_value  NUMERIC NOT NULL,
    unit          TEXT,
    owner         TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    updated_by    UUID REFERENCES lawyers(id),
    UNIQUE(year, kr_code, month)
);

CREATE INDEX IF NOT EXISTS idx_okr_targets_year ON okr_targets(year);
CREATE INDEX IF NOT EXISTS idx_okr_targets_kr   ON okr_targets(kr_code);

DROP TRIGGER IF EXISTS okr_targets_updated_at ON okr_targets;
CREATE TRIGGER okr_targets_updated_at
    BEFORE UPDATE ON okr_targets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 2. 手動實績（DB 還沒接的指標，例如 KR5 法0）
CREATE TABLE IF NOT EXISTS okr_manual_actuals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year          INTEGER NOT NULL,
    kr_code       TEXT NOT NULL,
    month         INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    actual_value  NUMERIC,
    notes         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    updated_by    UUID REFERENCES lawyers(id),
    UNIQUE(year, kr_code, month)
);

CREATE INDEX IF NOT EXISTS idx_okr_manual_year ON okr_manual_actuals(year);

DROP TRIGGER IF EXISTS okr_manual_actuals_updated_at ON okr_manual_actuals;
CREATE TRIGGER okr_manual_actuals_updated_at
    BEFORE UPDATE ON okr_manual_actuals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 3. 里程碑（KR4 合署到位 timeline、KR7 AI 教練 / 議題清單）
CREATE TABLE IF NOT EXISTS okr_milestones (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year          INTEGER NOT NULL,
    kr_code       TEXT NOT NULL,
    title         TEXT NOT NULL,
    target_date   DATE,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','in_progress','done','blocked')),
    owner         TEXT,
    notes         TEXT,
    sort_order    INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    updated_by    UUID REFERENCES lawyers(id)
);

CREATE INDEX IF NOT EXISTS idx_okr_milestones_year ON okr_milestones(year);
CREATE INDEX IF NOT EXISTS idx_okr_milestones_kr   ON okr_milestones(kr_code);

DROP TRIGGER IF EXISTS okr_milestones_updated_at ON okr_milestones;
CREATE TRIGGER okr_milestones_updated_at
    BEFORE UPDATE ON okr_milestones
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
--  RLS
--  讀：admin only（OKR 是高層追蹤工具，不對全員開放）
--  寫：admin only
-- ============================================================
ALTER TABLE okr_targets        ENABLE ROW LEVEL SECURITY;
ALTER TABLE okr_manual_actuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE okr_milestones     ENABLE ROW LEVEL SECURITY;

CREATE POLICY okr_targets_admin ON okr_targets
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY okr_manual_actuals_admin ON okr_manual_actuals
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY okr_milestones_admin ON okr_milestones
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

-- ============================================================
--  Seed：2026 年目標
--  KR1 諮詢營業額（不含法顧）+ 場次 + 退款上限
--  KR2 諮詢轉化率（萬/場）
--  KR3a 法顧新案：主動進線 / 介紹
--  KR3b 法顧續委任
--  KR4 合署：人數 / 轉案 / 自案
--  KR5 法0：營收 / 好友 / 轉諮 / 均單
--  KR6 月成本上限 / 年純利
--
--  月度同數值用 generate_series 展開 12 個月；月份 NULL = 年度目標
-- ============================================================

-- KR1：月諮詢營業額 1350 萬，年 16200 萬
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_revenue', NULL, 16200, '萬', '何泓儒'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr1_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_revenue', m, 1350, '萬', '何泓儒' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR1：月諮詢場次 380，年 4560
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_consult_count', NULL, 4560, '場', '何泓儒'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr1_consult_count' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_consult_count', m, 380, '場', '何泓儒' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR1：月退款金額上限 67.5 萬，年 810 萬
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_refund_cap', NULL, 810, '萬', '何泓儒'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr1_refund_cap' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr1_refund_cap', m, 67.5, '萬', '何泓儒' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR2：諮詢轉化率（萬/場），目標 ≥ 3
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr2_conversion', NULL, 3, '萬/場', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr2_conversion' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr2_conversion', m, 3, '萬/場', '雷皓明' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR3a：法顧主動進線 10 件/月、72 萬/月
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_active_cases', NULL, 120, '件', '吳泰儀'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3a_active_cases' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_active_cases', m, 10, '件', '吳泰儀' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_active_revenue', NULL, 864, '萬', '吳泰儀'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3a_active_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_active_revenue', m, 72, '萬', '吳泰儀' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR3a：介紹 2 件/月、15 萬/月
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_referral_cases', NULL, 24, '件', '黃杰'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3a_referral_cases' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_referral_cases', m, 2, '件', '黃杰' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_referral_revenue', NULL, 180, '萬', '黃杰'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3a_referral_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3a_referral_revenue', m, 15, '萬', '黃杰' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR3 法顧月營業額（含續委任）總目標 158 萬/月、1900 萬/年
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3_total_revenue', NULL, 1900, '萬', '吳泰儀'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3_total_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3_total_revenue', m, 158, '萬', '吳泰儀' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR3b：續委任 6 件/月、63 萬/月、年 760 萬
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3b_renewal_cases', NULL, 72, '件', '黃杰'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3b_renewal_cases' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3b_renewal_cases', m, 6, '件', '黃杰' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3b_renewal_amount', NULL, 760, '萬', '黃杰'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr3b_renewal_amount' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr3b_renewal_amount', m, 63, '萬', '黃杰' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR4：合署人數 15 位
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_partner_count', NULL, 15, '人', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr4_partner_count' AND month IS NULL);

-- KR4：轉案營業額 280 萬/月、自案 137.5 萬/月
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_referred_revenue', NULL, 3360, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr4_referred_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_referred_revenue', m, 280, '萬', '雷皓明' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_partner_self_revenue', NULL, 1650, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr4_partner_self_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_partner_self_revenue', m, 137.5, '萬', '雷皓明' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

-- KR4：處理案件總額 5000 萬、合署利潤 1500 萬
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_case_volume', NULL, 5000, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr4_case_volume' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr4_profit', NULL, 1500, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr4_profit' AND month IS NULL);

-- KR5：法0 月營收 666 萬、年 8000 萬、獲利 1900 萬
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr5_revenue', NULL, 8000, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr5_revenue' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr5_revenue', m, 666, '萬', '雷皓明' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr5_profit', NULL, 1900, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr5_profit' AND month IS NULL);

-- KR6：月成本上限 1450 萬、純利 4000 萬、總成本 17500 萬（1.75E）
INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr6_monthly_cost_cap', NULL, 17400, '萬', '吳泰儀'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr6_monthly_cost_cap' AND month IS NULL);

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr6_monthly_cost_cap', m, 1450, '萬', '吳泰儀' FROM generate_series(1,12) m
ON CONFLICT (year, kr_code, month) DO NOTHING;

INSERT INTO okr_targets (year, kr_code, month, target_value, unit, owner)
SELECT 2026, 'kr6_yearly_profit', NULL, 4000, '萬', '雷皓明'
WHERE NOT EXISTS (SELECT 1 FROM okr_targets WHERE year=2026 AND kr_code='kr6_yearly_profit' AND month IS NULL);

-- ============================================================
--  Seed 里程碑：KR4 合署到位 timeline、KR7 AI 教練團
-- ============================================================
INSERT INTO okr_milestones (year, kr_code, title, target_date, status, owner, sort_order)
SELECT * FROM (VALUES
    (2026, 'kr4_partner_count', '柯雪莉 4 月加入合署',           DATE '2026-04-01', 'done',        '雷皓明', 1),
    (2026, 'kr4_partner_count', '蘇萱 5 月轉合署',                DATE '2026-05-01', 'pending',     '雷皓明', 2),
    (2026, 'kr4_partner_count', '林家泓 6 月加入合署',            DATE '2026-06-01', 'pending',     '雷皓明', 3),
    (2026, 'kr4_partner_count', '陳奕靖 7 月加入合署',            DATE '2026-07-01', 'pending',     '雷皓明', 4),
    (2026, 'kr4_partner_count', '寧馨 7 月加入合署',              DATE '2026-07-01', 'pending',     '雷皓明', 5),
    (2026, 'kr4_partner_count', '司法官 2 位 8 月退下後加入',     DATE '2026-08-01', 'in_progress', '雷皓明', 6),
    (2026, 'kr7_ai',            'AI 教練團確認名單（薩爾文）',    NULL::DATE,        'in_progress', '雷皓明', 1),
    (2026, 'kr7_ai',            '飛宇 / 偉志 / 思蓓 / 杰峰 / JUDE 加入', NULL::DATE,        'in_progress', '雷皓明', 2),
    (2026, 'kr7_ai',            '股東四人加入 AI 教練團',         NULL::DATE,        'pending',     '雷皓明', 3),
    (2026, 'kr7_ai',            '釐清各部門想用 AI 解決的具體問題', NULL::DATE,        'pending',     '雷皓明', 4)
) AS v(year, kr_code, title, target_date, status, owner, sort_order)
WHERE NOT EXISTS (
    SELECT 1 FROM okr_milestones m
    WHERE m.year = v.year AND m.kr_code = v.kr_code AND m.title = v.title
);
