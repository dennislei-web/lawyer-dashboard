-- =====================================================
-- Migration: 客戶關係追蹤表整合
-- 1. 更新 role CHECK constraint，加入 manager 和 legal_staff
-- 2. 新增追蹤欄位到 consultation_cases
-- =====================================================

-- 1. 移除舊的 CHECK constraint，加入新的（包含 manager, legal_staff）
ALTER TABLE public.lawyers DROP CONSTRAINT IF EXISTS lawyers_role_check;
ALTER TABLE public.lawyers ADD CONSTRAINT lawyers_role_check
  CHECK (role IN ('lawyer', 'admin', 'manager', 'legal_staff'));

-- 2. 新增追蹤欄位
ALTER TABLE public.consultation_cases ADD COLUMN IF NOT EXISTS tracking_staff TEXT;
ALTER TABLE public.consultation_cases ADD COLUMN IF NOT EXISTS tracking_notes TEXT;
ALTER TABLE public.consultation_cases ADD COLUMN IF NOT EXISTS tracking_status TEXT;
