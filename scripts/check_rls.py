"""檢查 consultation_cases 的 RLS 政策和資料"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# 1. Check consultation_cases data count
print("=== consultation_cases 資料 ===")
resp = httpx.get(f"{url}/rest/v1/consultation_cases", params={"select": "id", "limit": "5"}, headers=headers)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"前5筆: {len(data)} 筆")
else:
    print(f"Error: {resp.text}")

# Count total
resp2 = httpx.head(f"{url}/rest/v1/consultation_cases", params={"select": "id"}, headers={**headers, "Prefer": "count=exact"})
total = resp2.headers.get("content-range", "unknown")
print(f"Total: {total}")

# 2. Check RLS policies via SQL
print("\n=== RLS 政策 ===")
sql = """
SELECT policyname, cmd, qual
FROM pg_policies
WHERE tablename = 'consultation_cases'
ORDER BY policyname;
"""
resp3 = httpx.post(f"{url}/rest/v1/rpc/exec_sql", json={"query": sql}, headers=headers)
if resp3.status_code == 200:
    for row in resp3.json():
        print(f"  Policy: {row['policyname']} | cmd: {row['cmd']} | qual: {row.get('qual','')[:100]}")
else:
    print(f"  exec_sql not available, trying pg_catalog...")
    # Try alternative approach
    resp4 = httpx.get(f"{url}/rest/v1/rpc/", headers=headers)
    print(f"  RPC status: {resp4.status_code}")

# 3. Check if get_my_role() function exists
print("\n=== 檢查 functions ===")
sql2 = "SELECT 1 FROM pg_proc WHERE proname = 'get_my_role';"
resp5 = httpx.post(f"{url}/rest/v1/rpc/get_my_role", json={}, headers=headers)
print(f"get_my_role(): status={resp5.status_code}, result={resp5.text[:200]}")

resp6 = httpx.post(f"{url}/rest/v1/rpc/can_view_all", json={}, headers=headers)
print(f"can_view_all(): status={resp6.status_code}, result={resp6.text[:200]}")

# 4. Check if consultation_cases has RLS enabled
print("\n=== RLS 啟用狀態 ===")
resp7 = httpx.get(f"{url}/rest/v1/consultation_cases", params={"select": "id,case_date,client_name,is_signed", "is_signed": "eq.false", "limit": "3", "order": "case_date.desc"}, headers=headers)
print(f"未簽約案件 (service key): status={resp7.status_code}")
if resp7.status_code == 200:
    for c in resp7.json():
        print(f"  {c.get('case_date')} | {c.get('client_name')} | signed={c.get('is_signed')}")
else:
    print(f"  Error: {resp7.text[:200]}")

# 5. Test as admin user (simulate login)
print("\n=== 模擬管理員登入 ===")
admin_email = "dennis.lei@010.tw"
# Get admin's auth token
auth_resp = httpx.post(f"{url}/auth/v1/token?grant_type=password", json={
    "email": admin_email,
    "password": os.environ.get("DEFAULT_PASSWORD", "ChangeMe123!")
}, headers={"apikey": key, "Content-Type": "application/json"})
print(f"Admin login: status={auth_resp.status_code}")
if auth_resp.status_code == 200:
    token = auth_resp.json()["access_token"]
    user_headers = {"apikey": key, "Authorization": f"Bearer {token}"}

    # Try fetching cases as admin
    cases_resp = httpx.get(f"{url}/rest/v1/consultation_cases", params={"select": "id", "limit": "5"}, headers=user_headers)
    print(f"Cases as admin: status={cases_resp.status_code}, count={len(cases_resp.json()) if cases_resp.status_code == 200 else 'N/A'}")
    if cases_resp.status_code != 200:
        print(f"  Error: {cases_resp.text[:300]}")

    # Try fetching lawyers as admin
    law_resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name", "limit": "3"}, headers=user_headers)
    print(f"Lawyers as admin: status={law_resp.status_code}, count={len(law_resp.json()) if law_resp.status_code == 200 else 'N/A'}")
    if law_resp.status_code != 200:
        print(f"  Error: {law_resp.text[:300]}")
else:
    print(f"  Login failed: {auth_resp.text[:200]}")
