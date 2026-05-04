-- ============================================================
--  法律顧問品牌分類表
--  存「官網法顧品牌」追蹤表的公司 → 類別 對應
--  （資料量小、變動頻率低，採 seed + 手動更新；不接 Apps Script daily sync）
-- ============================================================

CREATE TABLE IF NOT EXISTS advisor_company_categories (
    company_name TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    note         TEXT,
    updated_at   TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_company_categories ENABLE ROW LEVEL SECURITY;

CREATE POLICY advisor_company_categories_select ON advisor_company_categories
    FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY advisor_company_categories_admin ON advisor_company_categories
    FOR ALL USING (is_admin()) WITH CHECK (is_admin());

COMMENT ON TABLE advisor_company_categories IS
  '官網法顧品牌追蹤表的分類映射（公司 → 類別）。是否同意刊載刻意不收。';
