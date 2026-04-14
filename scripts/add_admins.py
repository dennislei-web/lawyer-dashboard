"""新增/升級管理員帳號"""
import os, io, sys
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "ChangeMe123!")
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

admins = [
    {"name": "蘇思蓓", "email": "sibei.su@zhelu.tw", "office": "喆律法律事務所"},
    {"name": "客戶關係部", "email": "CRM@zhelu.tw", "office": "喆律法律事務所"},
]

for admin in admins:
    name = admin["name"]
    email = admin["email"]
    office = admin["office"]
    print(f"\n{'='*40}")
    print(f"處理：{name} ({email})")
    print(f"{'='*40}")

    # 1. Check if already in lawyers table
    resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "*", "email": f"eq.{email}"}, headers=headers)
    existing = resp.json()

    if existing:
        lawyer = existing[0]
        print(f"  ✓ 已在 lawyers 表, id={lawyer['id']}, role={lawyer['role']}")

        # Update to admin if not already
        if lawyer['role'] != 'admin':
            upd = httpx.patch(f"{url}/rest/v1/lawyers", params={"email": f"eq.{email}"}, json={
                "role": "admin",
                "can_view_all": True,
            }, headers=headers)
            print(f"  → 升級為 admin: {upd.status_code}")
        elif not lawyer.get('can_view_all'):
            upd = httpx.patch(f"{url}/rest/v1/lawyers", params={"email": f"eq.{email}"}, json={
                "can_view_all": True,
            }, headers=headers)
            print(f"  → 開啟 can_view_all: {upd.status_code}")
        else:
            print(f"  ✓ 已是 admin + can_view_all")

        lawyer_id = lawyer['id']
    else:
        # Insert new lawyer
        insert_headers = {**headers, "Prefer": "return=representation"}
        resp = httpx.post(f"{url}/rest/v1/lawyers", json={
            "name": name,
            "email": email,
            "office": office,
            "role": "admin",
            "is_active": True,
            "can_view_all": True,
        }, headers=insert_headers)
        if resp.status_code in (200, 201):
            lawyer_id = resp.json()[0]["id"]
            print(f"  ✓ 新增到 lawyers 表, id={lawyer_id}, role=admin")
        else:
            print(f"  ✗ 新增失敗: {resp.status_code} {resp.text}")
            continue

    # 2. Check/Create Auth user
    auth_resp = httpx.get(f"{url}/auth/v1/admin/users", headers=headers, params={"page": 1, "per_page": 500})
    users = auth_resp.json().get("users", [])
    auth_user = next((u for u in users if u["email"].lower() == email.lower()), None)

    if auth_user:
        auth_user_id = auth_user["id"]
        print(f"  ✓ Auth 帳號已存在, uid={auth_user_id}")
    else:
        # Create Auth user
        create_resp = httpx.post(f"{url}/auth/v1/admin/users", json={
            "email": email,
            "password": DEFAULT_PASSWORD,
            "email_confirm": True,
        }, headers=headers)
        if create_resp.status_code in (200, 201):
            auth_user_id = create_resp.json()["id"]
            print(f"  ✓ 已建立 Auth 帳號, uid={auth_user_id}")
        else:
            print(f"  ✗ Auth 建立失敗: {create_resp.status_code} {create_resp.text}")
            continue

    # 3. Bind auth_user_id
    upd = httpx.patch(f"{url}/rest/v1/lawyers", params={"email": f"eq.{email}"}, json={
        "auth_user_id": auth_user_id
    }, headers=headers)
    if upd.status_code in (200, 204):
        print(f"  ✓ 已綁定 auth_user_id")
    else:
        print(f"  ✗ 綁定失敗: {upd.status_code} {upd.text}")

    print(f"\n  登入資訊：")
    print(f"    Email: {email}")
    print(f"    密碼: {DEFAULT_PASSWORD}")
