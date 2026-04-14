import httpx, os, io, sys
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "name,email,auth_user_id,is_active", "order": "name"}, headers=headers)
for l in resp.json():
    has_auth = "Y" if l.get("auth_user_id") else "N"
    print(f"{l['name']:>6} | {l['email']:>30} | active={l.get('is_active')} | auth={has_auth}")

# Check Supabase Auth for sibei.su@zhelu.tw
print("\n--- Checking Auth for sibei.su@zhelu.tw ---")
try:
    auth_resp = httpx.get(
        f"{url}/auth/v1/admin/users",
        headers={**headers, "Content-Type": "application/json"},
        params={"page": 1, "per_page": 500},
    )
    users = auth_resp.json().get("users", [])
    for u in users:
        if "su" in u.get("email", ""):
            print(f"  Auth user: {u['email']} | id={u['id']}")
except Exception as e:
    print(f"  Error: {e}")
