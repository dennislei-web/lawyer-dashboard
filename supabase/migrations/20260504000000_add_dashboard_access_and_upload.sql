-- ============================================
-- 新增 dashboard_access (TEXT[]) 與 can_upload (BOOLEAN) 欄位
--
-- 用途：
--   - 部門主管（role='manager'）可被授予部分儀表板的存取權限
--     dashboard_access 為文字陣列，元素為儀表板 key：
--       consultation / revenue / finance / advisor / partners / funnel
--   - 部門主管的「資料上傳」權限改為獨立 flag，可單獨開關
--
-- 規則（前端強制；DB 只負責欄位儲存）：
--   - admin   → 全部儀表板 + 上傳，忽略 dashboard_access / can_upload
--   - manager → 依 dashboard_access 決定可見儀表板；can_upload 決定上傳
--   - lawyer  → 僅諮詢分析，無上傳
-- ============================================

ALTER TABLE public.lawyers
  ADD COLUMN IF NOT EXISTS dashboard_access TEXT[] DEFAULT ARRAY['consultation']::TEXT[];

ALTER TABLE public.lawyers
  ADD COLUMN IF NOT EXISTS can_upload BOOLEAN DEFAULT false;

-- 既有 manager 帳號保留原本的「諮詢分析+上傳」配置
UPDATE public.lawyers
   SET dashboard_access = ARRAY['consultation']::TEXT[],
       can_upload = true
 WHERE role = 'manager'
   AND (dashboard_access IS NULL OR cardinality(dashboard_access) = 0);

-- admin 帳號的 dashboard_access 雖然會被前端忽略，仍補一份完整清單避免空陣列誤判
UPDATE public.lawyers
   SET dashboard_access = ARRAY['consultation','revenue','finance','advisor','partners','funnel']::TEXT[],
       can_upload = true
 WHERE role = 'admin';
