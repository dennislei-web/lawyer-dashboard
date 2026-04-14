-- ============================================
-- sync_status 同步狀態記錄表
-- ============================================

CREATE TABLE IF NOT EXISTS public.sync_status (
  id TEXT PRIMARY KEY DEFAULT 'daily_update',
  status TEXT NOT NULL DEFAULT 'pending',        -- success / error / running
  message TEXT,
  scraped_months TEXT,                           -- e.g. "2026-03"
  rows_scraped INTEGER DEFAULT 0,
  rows_updated INTEGER DEFAULT 0,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.sync_status ENABLE ROW LEVEL SECURITY;

-- 所有登入使用者都可以讀取同步狀態
CREATE POLICY "sync_status_select" ON public.sync_status
  FOR SELECT USING (auth.uid() IS NOT NULL);

-- 只有 service_role key 可以寫入（腳本用）
CREATE POLICY "sync_status_modify" ON public.sync_status
  FOR ALL USING (false);

-- 初始化一筆預設資料
INSERT INTO public.sync_status (id, status, message)
VALUES ('daily_update', 'pending', '尚未執行過同步')
ON CONFLICT (id) DO NOTHING;
