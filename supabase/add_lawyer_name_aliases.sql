-- name alias 機制：CRM 同一人多名（typo）合併
-- 用法：dashboard preprocessing 階段，看到 alias_name 就替換成 canonical_name

CREATE TABLE IF NOT EXISTS lawyer_name_aliases (
  alias_name      TEXT PRIMARY KEY,
  canonical_name  TEXT NOT NULL,
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS：dashboard 公開讀
ALTER TABLE lawyer_name_aliases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow read" ON lawyer_name_aliases;
CREATE POLICY "allow read" ON lawyer_name_aliases FOR SELECT USING (true);

INSERT INTO lawyer_name_aliases (alias_name, canonical_name, note) VALUES
  ('王悅璇', '王悦璇', 'CRM typo：悅(心字底) vs 悦 — 2026-05-26 雷皓明確認同一人')
ON CONFLICT (alias_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name, note = EXCLUDED.note;

SELECT * FROM lawyer_name_aliases ORDER BY alias_name;
