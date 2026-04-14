"""Execute can_view_all migration via Supabase REST API"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]

# Use the Supabase Management API or direct SQL
# Since we can't run raw SQL via REST, we'll do it step by step via REST API

headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# Step 1: Add column via RPC if possible, or check if it exists
# Test if can_view_all already exists
resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "can_view_all", "limit": "1"}, headers=headers)
if resp.status_code == 200:
    print("✓ can_view_all 欄位已存在")
else:
    print("✗ can_view_all 欄位不存在，需要手動執行 SQL")
    print(f"  錯誤: {resp.status_code} {resp.text}")
    print("\n請到 Supabase Dashboard → SQL Editor 執行：")
    print("  ALTER TABLE public.lawyers ADD COLUMN IF NOT EXISTS can_view_all BOOLEAN DEFAULT false;")
    print("\n然後重新執行此腳本。")
    sys.exit(1)

# Step 2: The RLS policies also need SQL execution
# Let's check what we can verify
print("\n⚠️  RLS 政策需要在 Supabase Dashboard → SQL Editor 執行以下 SQL：")
print("=" * 60)

sql = """
-- 新增 RLS 政策：允許 can_view_all=true 的律師看全部資料

-- lawyers 表
CREATE POLICY "lawyers_select_view_all" ON public.lawyers
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers AS l
      WHERE l.auth_user_id = auth.uid() AND l.can_view_all = true
    )
  );

-- monthly_stats 表
CREATE POLICY "monthly_stats_select_view_all" ON public.monthly_stats
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );

-- consultation_cases 表 (重建)
DROP POLICY IF EXISTS "cases_select" ON public.consultation_cases;
CREATE POLICY "cases_select" ON public.consultation_cases
  FOR SELECT USING (
    lawyer_id IN (SELECT id FROM public.lawyers WHERE auth_user_id = auth.uid())
    OR public.get_my_role() = 'admin'
    OR EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );

-- consultation_logs 表
CREATE POLICY "consultation_logs_select_view_all" ON public.consultation_logs
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.lawyers
      WHERE auth_user_id = auth.uid() AND can_view_all = true
    )
  );
"""
print(sql)
