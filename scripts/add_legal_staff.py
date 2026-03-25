"""新增法務人員到 lawyers 表（role = legal_staff）"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation,resolution=merge-duplicates",
}

# 需要新增的法務人員（方浚煜、李音忻已存在）
new_staff = [
    {"name": "江欣柔", "email": "legal_staff_江欣柔@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
    {"name": "黃逸庭", "email": "legal_staff_黃逸庭@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
    {"name": "謝依璇", "email": "legal_staff_謝依璇@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
    {"name": "賴佳瑩", "email": "legal_staff_賴佳瑩@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
    {"name": "曾靖雯", "email": "legal_staff_曾靖雯@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
    {"name": "董沐穎", "email": "legal_staff_董沐穎@zhelu.tw", "role": "legal_staff", "office": "喆律法律事務所", "is_active": True},
]

# 也將已存在的方浚煜、李音忻更新為 legal_staff 角色
existing_staff_to_update = ["方浚煜", "李音忻"]

print("=== 新增法務人員 ===\n")

# Insert new staff
for s in new_staff:
    resp = httpx.post(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        headers=headers,
        json=s,
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"  ✅ {s['name']} 新增成功 (id={data[0]['id'] if data else '?'})")
    elif resp.status_code == 409 or "duplicate" in resp.text.lower():
        print(f"  ⚠️  {s['name']} 已存在，跳過")
    else:
        print(f"  ❌ {s['name']} 失敗: {resp.status_code} {resp.text[:200]}")

# Update existing resigned staff to legal_staff role
print("\n=== 更新已存在人員角色 ===\n")
for name in existing_staff_to_update:
    resp = httpx.patch(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        headers=headers,
        params={"name": f"eq.{name}"},
        json={"role": "legal_staff"},
    )
    if resp.status_code in (200, 204):
        print(f"  ✅ {name} 角色已更新為 legal_staff")
    else:
        print(f"  ❌ {name} 更新失敗: {resp.status_code} {resp.text[:200]}")

print("\n完成！")
