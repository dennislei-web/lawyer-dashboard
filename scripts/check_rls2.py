"""檢查 admin 帳號 + consultation_cases RLS"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# 1. Find admin user in Auth
print("=== Auth 使用者 ===")
auth_resp = httpx.get(f"{url}/auth/v1/admin/users", headers=headers, params={"page": 1, "per_page": 100})
users = auth_resp.json().get("users", [])
admin_uid = None
for u in users:
    if "dennis" in u.get("email", ""):
        admin_uid = u["id"]
        print(f"  Admin: {u['email']} | id={u['id']}")

# 2. Check admin's lawyer record
print("\n=== Admin lawyer record ===")
resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "*", "email": "eq.dennis.lei@010.tw"}, headers=headers)
if resp.status_code == 200 and resp.json():
    admin = resp.json()[0]
    print(f"  name={admin['name']} role={admin['role']} auth_user_id={admin.get('auth_user_id')} can_view_all={admin.get('can_view_all')}")
    # Check if auth_user_id matches
    if admin.get('auth_user_id') != admin_uid:
        print(f"  ⚠ auth_user_id mismatch! DB={admin.get('auth_user_id')}, Auth={admin_uid}")

# 3. Reset admin password and test login
print("\n=== 重設密碼並測試 ===")
if admin_uid:
    reset = httpx.put(f"{url}/auth/v1/admin/users/{admin_uid}", json={
        "password": "ChangeMe123!"
    }, headers=headers)
    print(f"Reset password: {reset.status_code}")

    # Now try login
    login = httpx.post(f"{url}/auth/v1/token?grant_type=password", json={
        "email": "dennis.lei@010.tw",
        "password": "ChangeMe123!"
    }, headers={"apikey": key, "Content-Type": "application/json"})
    print(f"Login: {login.status_code}")

    if login.status_code == 200:
        token = login.json()["access_token"]
        user_headers = {"apikey": key, "Authorization": f"Bearer {token}"}

        # Test consultation_cases
        cases_resp = httpx.get(f"{url}/rest/v1/consultation_cases",
            params={"select": "id,case_date,client_name,is_signed", "limit": "5", "order": "case_date.desc"},
            headers=user_headers)
        print(f"\nCases as admin: status={cases_resp.status_code}")
        if cases_resp.status_code == 200:
            data = cases_resp.json()
            print(f"  返回 {len(data)} 筆")
            for c in data:
                print(f"  {c.get('case_date')} | {c.get('client_name')} | signed={c.get('is_signed')}")
        else:
            print(f"  Error: {cases_resp.text[:300]}")

        # Test count with head
        cases_head = httpx.head(f"{url}/rest/v1/consultation_cases",
            params={"select": "id"},
            headers={**user_headers, "Prefer": "count=exact"})
        print(f"  Total visible: {cases_head.headers.get('content-range', 'unknown')}")

        # Test lawyers
        law_resp = httpx.get(f"{url}/rest/v1/lawyers",
            params={"select": "id,name", "limit": "3"},
            headers=user_headers)
        print(f"\nLawyers as admin: status={law_resp.status_code}, count={len(law_resp.json()) if law_resp.status_code == 200 else 'N/A'}")
    else:
        print(f"  Login error: {login.text[:200]}")
