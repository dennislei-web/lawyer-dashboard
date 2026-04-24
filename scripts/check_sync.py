"""檢查同步狀態 + GitHub Actions 執行紀錄"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

# 1. 檢查 sync_status
print("=== sync_status 表 ===")
resp = httpx.get(f"{url}/rest/v1/sync_status", params={"select": "*", "order": "updated_at.desc", "limit": "5"}, headers=headers)
if resp.status_code == 200:
    for s in resp.json():
        print(f"  {s.get('id')} | status={s.get('status')} | {s.get('message')} | updated={s.get('updated_at')} | finished={s.get('finished_at')}")
else:
    print(f"  Error: {resp.status_code} {resp.text[:200]}")

# 2. 檢查 consultation_cases 最新資料日期
print("\n=== consultation_cases 最新日期 ===")
resp2 = httpx.get(f"{url}/rest/v1/consultation_cases", params={"select": "case_date", "order": "case_date.desc", "limit": "5"}, headers=headers)
if resp2.status_code == 200:
    for c in resp2.json():
        print(f"  {c['case_date']}")

# 3. 檢查 monthly_stats 最新月份
print("\n=== monthly_stats 最新月份 ===")
resp3 = httpx.get(f"{url}/rest/v1/monthly_stats", params={"select": "month,consult_count,signed_count", "order": "month.desc", "limit": "10"}, headers=headers)
if resp3.status_code == 200:
    months_seen = set()
    for s in resp3.json():
        m = s['month']
        if m not in months_seen:
            months_seen.add(m)
            print(f"  {m}: consult={s['consult_count']} signed={s['signed_count']}")
        if len(months_seen) >= 3:
            break

# 4. 檢查 consultation_cases 中 2026-03 的最新筆數
print("\n=== 2026-03 consultation_cases ===")
resp4 = httpx.head(f"{url}/rest/v1/consultation_cases", params={"select": "id", "case_date": "gte.2026-03-01"}, headers={**headers, "Prefer": "count=exact"})
print(f"  2026-03 total: {resp4.headers.get('content-range', 'unknown')}")

# 2026-03-18 specifically
resp5 = httpx.get(f"{url}/rest/v1/consultation_cases", params={"select": "case_date,client_name,is_signed", "case_date": "eq.2026-03-18", "limit": "5"}, headers=headers)
if resp5.status_code == 200:
    data = resp5.json()
    print(f"  2026-03-18: {len(data)} 筆 (showing first 5)")
    for c in data:
        print(f"    {c['case_date']} | {c['client_name']} | signed={c['is_signed']}")
