"""檢查 consultation_cases 欄位 + 模擬前端 fetch"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
anon_key = "sb_publishable_NvTWZM6IGgc_Jn8iCXFvaA_QnvJsstM"

# Login as admin with ANON key
login = httpx.post(f"{url}/auth/v1/token?grant_type=password", json={
    "email": "dennis.lei@010.tw",
    "password": "ChangeMe123!"
}, headers={"apikey": anon_key, "Content-Type": "application/json"})
token = login.json()["access_token"]
user_headers = {"apikey": anon_key, "Authorization": f"Bearer {token}"}

# 1. Test exact same select as frontend
print("=== 模擬前端 select (完整欄位) ===")
selectCols = "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected,meeting_record,transcript"
resp = httpx.get(f"{url}/rest/v1/consultation_cases",
    params={"select": selectCols, "limit": "1"},
    headers=user_headers)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"OK, {len(data)} rows")
    if data:
        print(f"Columns: {list(data[0].keys())}")
else:
    print(f"ERROR: {resp.text[:500]}")

# 2. Test fallback select
print("\n=== 模擬前端 fallback select ===")
selectCols2 = "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,meeting_record,transcript"
resp2 = httpx.get(f"{url}/rest/v1/consultation_cases",
    params={"select": selectCols2, "limit": "1"},
    headers=user_headers)
print(f"Status: {resp2.status_code}")
if resp2.status_code == 200:
    data = resp2.json()
    print(f"OK, {len(data)} rows")
    if data:
        print(f"Columns: {list(data[0].keys())}")
else:
    print(f"ERROR: {resp2.text[:500]}")

# 3. Test with select *
print("\n=== select * ===")
resp3 = httpx.get(f"{url}/rest/v1/consultation_cases",
    params={"select": "*", "limit": "1"},
    headers=user_headers)
print(f"Status: {resp3.status_code}")
if resp3.status_code == 200:
    data = resp3.json()
    if data:
        print(f"All columns: {list(data[0].keys())}")
else:
    print(f"ERROR: {resp3.text[:500]}")

# 4. Test pagination (same as frontend loadDashboard)
print("\n=== 模擬前端分頁 fetch ===")
casesFetched = []
frm = 0
pageSize = 1000
while True:
    resp4 = httpx.get(f"{url}/rest/v1/consultation_cases",
        params={"select": selectCols, "order": "case_date.desc", "offset": str(frm), "limit": str(pageSize)},
        headers=user_headers)
    if resp4.status_code != 200:
        print(f"Page fetch error at offset {frm}: {resp4.status_code} {resp4.text[:200]}")
        break
    page = resp4.json()
    if not page:
        break
    casesFetched.extend(page)
    print(f"  Fetched page at offset {frm}: {len(page)} rows")
    if len(page) < pageSize:
        break
    frm += pageSize

print(f"Total fetched: {len(casesFetched)}")
