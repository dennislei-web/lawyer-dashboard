"""新增律師到 lawyers 表並建立 Auth 帳號 (httpx 版)"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "ChangeMe123!")
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

name = "蘇思蓓"
email = "sibei.su@zhelu.tw"
office = "喆律法律事務所"

# 1. Check if already in lawyers table
resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id", "email": f"eq.{email}"}, headers=headers)
if resp.json():
    print(f"{name} 已存在於 lawyers 表")
else:
    # Insert into lawyers table
    insert_headers = {**headers, "Content-Type": "application/json", "Prefer": "return=representation"}
    resp = httpx.post(f"{url}/rest/v1/lawyers", json={
        "name": name,
        "email": email,
        "office": office,
        "role": "lawyer",
        "is_active": True,
    }, headers=insert_headers)
    if resp.status_code in (200, 201):
        lawyer_id = resp.json()[0]["id"]
        print(f"✓ 已新增 {name} 到 lawyers 表, id={lawyer_id}")
    else:
        print(f"✗ 新增失敗: {resp.status_code} {resp.text}")
        sys.exit(1)

# 2. Create Auth user
auth_headers = {**headers, "Content-Type": "application/json"}
auth_resp = httpx.post(f"{url}/auth/v1/admin/users", json={
    "email": email,
    "password": DEFAULT_PASSWORD,
    "email_confirm": True,
}, headers=auth_headers)

if auth_resp.status_code in (200, 201):
    auth_user_id = auth_resp.json()["id"]
    print(f"✓ 已建立 Auth 帳號, uid={auth_user_id}")

    # Update lawyers table with auth_user_id
    update_headers = {**headers, "Content-Type": "application/json"}
    upd = httpx.patch(f"{url}/rest/v1/lawyers", params={"email": f"eq.{email}"}, json={
        "auth_user_id": auth_user_id
    }, headers=update_headers)
    if upd.status_code in (200, 204):
        print(f"✓ 已綁定 auth_user_id")
    else:
        print(f"✗ 綁定失敗: {upd.status_code} {upd.text}")
else:
    print(f"Auth 建立結果: {auth_resp.status_code} {auth_resp.text}")

print(f"\n登入資訊：")
print(f"  Email: {email}")
print(f"  密碼: {DEFAULT_PASSWORD}")
