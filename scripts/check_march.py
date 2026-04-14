"""檢查 3 月 monthly_stats 詳情"""
import os, io, sys
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

# 1. monthly_stats for 2026-03 (all lawyers)
print("=== monthly_stats 2026-03 (全部律師) ===")
resp = httpx.get(f"{url}/rest/v1/monthly_stats", params={
    "select": "month,consult_count,signed_count,revenue,collected,lawyer_id",
    "month": "eq.2026-03",
    "order": "consult_count.desc"
}, headers=headers)
total_consult = 0
total_signed = 0
if resp.status_code == 200:
    data = resp.json()
    print(f"  共 {len(data)} 位律師有 3 月資料")
    for s in data[:5]:
        total_consult += s['consult_count']
        total_signed += s['signed_count']
        print(f"  lawyer={s['lawyer_id'][:8]}... consult={s['consult_count']} signed={s['signed_count']} rev={s.get('revenue',0)} col={s.get('collected',0)}")
    for s in data[5:]:
        total_consult += s['consult_count']
        total_signed += s['signed_count']
    print(f"  === 合計: consult={total_consult}, signed={total_signed} ===")

# 2. consultation_cases for 2026-03 (count by date)
print("\n=== consultation_cases 2026-03 每日筆數 ===")
resp2 = httpx.get(f"{url}/rest/v1/consultation_cases", params={
    "select": "case_date",
    "case_date": "gte.2026-03-01",
    "order": "case_date.desc"
}, headers=headers)
if resp2.status_code == 200:
    dates = {}
    for c in resp2.json():
        d = c['case_date']
        dates[d] = dates.get(d, 0) + 1
    for d in sorted(dates.keys(), reverse=True)[:10]:
        print(f"  {d}: {dates[d]} 筆")
    print(f"  3月合計: {sum(dates.values())} 筆 consultation_cases")

# 3. Check sync_status updated_at
print("\n=== 最近同步紀錄 ===")
resp3 = httpx.get(f"{url}/rest/v1/sync_status", params={"select": "*", "order": "updated_at.desc", "limit": "3"}, headers=headers)
if resp3.status_code == 200:
    for s in resp3.json():
        print(f"  {s.get('status')} | {s.get('message')} | scraped_months={s.get('scraped_months')} | rows_scraped={s.get('rows_scraped')} | rows_updated={s.get('rows_updated')} | finished={s.get('finished_at')}")

# 4. monthly_stats for 2026-03 updated_at
print("\n=== monthly_stats 2026-03 最後更新時間 ===")
resp4 = httpx.get(f"{url}/rest/v1/monthly_stats", params={
    "select": "updated_at",
    "month": "eq.2026-03",
    "order": "updated_at.desc",
    "limit": "1"
}, headers=headers)
if resp4.status_code == 200 and resp4.json():
    print(f"  最後更新: {resp4.json()[0]['updated_at']}")
