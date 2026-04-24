"""深入檢查 admin 登入後的 RLS + get_my_role()"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
anon_key = "sb_publishable_NvTWZM6IGgc_Jn8iCXFvaA_QnvJsstM"
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# Login as admin with ANON key (like frontend does)
print("=== 以 anon key 登入 (模擬前端) ===")
login = httpx.post(f"{url}/auth/v1/token?grant_type=password", json={
    "email": "dennis.lei@010.tw",
    "password": "ChangeMe123!"
}, headers={"apikey": anon_key, "Content-Type": "application/json"})
print(f"Login status: {login.status_code}")

if login.status_code != 200:
    print(f"Error: {login.text[:300]}")
    sys.exit(1)

token = login.json()["access_token"]
user_id = login.json()["user"]["id"]
print(f"User ID: {user_id}")

user_headers = {"apikey": anon_key, "Authorization": f"Bearer {token}"}

# 1. Check lawyers table access
print("\n=== lawyers 表 ===")
law_resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name,role,can_view_all,auth_user_id", "auth_user_id": f"eq.{user_id}"}, headers=user_headers)
print(f"Status: {law_resp.status_code}")
if law_resp.status_code == 200:
    data = law_resp.json()
    print(f"找到 {len(data)} 筆")
    for l in data:
        print(f"  {l['name']} role={l['role']} can_view_all={l.get('can_view_all')}")
else:
    print(f"Error: {law_resp.text[:300]}")

# 2. Check get_my_role()
print("\n=== get_my_role() ===")
role_resp = httpx.post(f"{url}/rest/v1/rpc/get_my_role", json={}, headers={**user_headers, "Content-Type": "application/json"})
print(f"Status: {role_resp.status_code}, Result: {role_resp.text[:100]}")

# 3. Check can_view_all()
print("\n=== can_view_all() ===")
cva_resp = httpx.post(f"{url}/rest/v1/rpc/can_view_all", json={}, headers={**user_headers, "Content-Type": "application/json"})
print(f"Status: {cva_resp.status_code}, Result: {cva_resp.text[:100]}")

# 4. Check consultation_cases
print("\n=== consultation_cases ===")
cases_resp = httpx.get(f"{url}/rest/v1/consultation_cases",
    params={"select": "id,case_date,client_name,is_signed", "limit": "5", "order": "case_date.desc"},
    headers=user_headers)
print(f"Status: {cases_resp.status_code}")
if cases_resp.status_code == 200:
    data = cases_resp.json()
    print(f"返回 {len(data)} 筆")
    for c in data:
        print(f"  {c.get('case_date')} | {c.get('client_name')} | signed={c.get('is_signed')}")
else:
    print(f"Error: {cases_resp.text[:500]}")

# Total count
cases_head = httpx.head(f"{url}/rest/v1/consultation_cases",
    params={"select": "id"},
    headers={**user_headers, "Prefer": "count=exact"})
print(f"Total visible: {cases_head.headers.get('content-range', 'unknown')}")

# 5. Check unsigned cases specifically
print("\n=== 未簽約案件 (is_signed=false, 近1個月) ===")
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
unsigned_resp = httpx.get(f"{url}/rest/v1/consultation_cases",
    params={"select": "id,case_date,client_name", "is_signed": "eq.false", "case_date": f"gte.{cutoff}", "limit": "5", "order": "case_date.desc"},
    headers=user_headers)
print(f"Status: {unsigned_resp.status_code}")
if unsigned_resp.status_code == 200:
    data = unsigned_resp.json()
    print(f"返回 {len(data)} 筆")
    for c in data:
        print(f"  {c.get('case_date')} | {c.get('client_name')}")
else:
    print(f"Error: {unsigned_resp.text[:300]}")

# 6. Check all lawyers (for admin view)
print("\n=== 所有律師 (admin view) ===")
all_law = httpx.get(f"{url}/rest/v1/lawyers",
    params={"select": "id,name,is_active", "order": "name"},
    headers=user_headers)
print(f"Status: {all_law.status_code}")
if all_law.status_code == 200:
    data = all_law.json()
    print(f"共 {len(data)} 位律師")
else:
    print(f"Error: {all_law.text[:300]}")
