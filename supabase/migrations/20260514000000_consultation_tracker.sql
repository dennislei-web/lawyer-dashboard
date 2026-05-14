-- ============================================================
-- 1-on-1 諮詢追蹤系統（僅雷皓明可見）
-- ============================================================
-- 目的：雷皓明對所有諮詢律師做 1-on-1 追蹤的私人儀表板
-- 權限：僅 dennis.lei@010.tw 可讀/寫 tracker rows 與 briefs storage

-- ============================================================
-- 1. consultation_tracker：每律師一行的追蹤紀錄
-- ============================================================
CREATE TABLE IF NOT EXISTS consultation_tracker (
  lawyer_id          UUID PRIMARY KEY REFERENCES lawyers(id) ON DELETE CASCADE,
  pattern_group      TEXT,                          -- 例：'A_quoting_outsource', 'B_no_close', etc.
  target_text        TEXT,                          -- 個人化目標（自由文字）
  one_on_one_date    DATE,                          -- 已完成的 1-on-1 日期
  one_on_one_status  TEXT DEFAULT 'pending',        -- pending | scheduled | done | followup
  next_action        TEXT,                          -- 下一步動作
  notes              TEXT,                          -- 自由備註
  updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracker_status ON consultation_tracker(one_on_one_status);

-- ============================================================
-- 2. RLS：僅雷皓明 (dennis.lei@010.tw) 能讀/寫
-- ============================================================
ALTER TABLE consultation_tracker ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tracker_dennis_only ON consultation_tracker;
CREATE POLICY tracker_dennis_only ON consultation_tracker
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lawyers.email = 'dennis.lei@010.tw'
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lawyers.email = 'dennis.lei@010.tw'
    )
  );

-- ============================================================
-- 3. Storage bucket: briefs（私有 + 僅雷皓明可讀）
-- ============================================================
INSERT INTO storage.buckets (id, name, public)
VALUES ('briefs', 'briefs', false)
ON CONFLICT (id) DO NOTHING;

-- Storage policies (storage.objects)
DROP POLICY IF EXISTS "briefs_read_dennis" ON storage.objects;
CREATE POLICY "briefs_read_dennis" ON storage.objects
  FOR SELECT
  USING (
    bucket_id = 'briefs'
    AND EXISTS (
      SELECT 1 FROM lawyers
      WHERE lawyers.auth_user_id = auth.uid()
        AND lawyers.email = 'dennis.lei@010.tw'
    )
  );

-- service_role 寫入 (Python upload 腳本用) — 不需 policy，service key 繞 RLS

-- ============================================================
-- 4. updated_at trigger
-- ============================================================
CREATE OR REPLACE FUNCTION tracker_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tracker_updated_at ON consultation_tracker;
CREATE TRIGGER trg_tracker_updated_at
  BEFORE UPDATE ON consultation_tracker
  FOR EACH ROW
  EXECUTE FUNCTION tracker_touch_updated_at();
