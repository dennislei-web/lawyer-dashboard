import httpx, os, io, sys
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

TARGET_IDS = {
    "洪琬琪": "0ec39f62-859d-4892-8939-5475fb8251f9",
    "張又仁": "4ba425e3-dd3b-4a1e-a13b-23d1a00a78de",
    "劉奕靖": "396c3550-ff13-4ad2-af72-1583662b4f7d",
}

# 1) monthly_stats 樣本 — 看 month 欄位格式
print("[1] monthly_stats 樣本（格式檢查）")
r = httpx.get(f"{url}/rest/v1/monthly_stats",
              params={"select": "*", "order": "month.desc", "limit": "10"},
              headers=headers)
for s in r.json():
    print(f"  {s}")

# 2) 目標律師 115/01-03 的 monthly_stats
print("\n[2] 目標律師 115/01-03 的 monthly_stats")
for name, lid in TARGET_IDS.items():
    r = httpx.get(f"{url}/rest/v1/monthly_stats",
                  params={
                      "select": "month,consult_count,signed_count,sign_rate,revenue,collected,updated_at",
                      "lawyer_id": f"eq.{lid}",
                      "order": "month.desc",
                      "limit": "12",
                  },
                  headers=headers)
    rows = r.json()
    print(f"\n  === {name} === 共 {len(rows)} 筆月度統計")
    for x in rows:
        print(f"    month={x['month']:<10} | consult={x['consult_count']:>3} signed={x['signed_count']:>3} "
              f"rate={x['sign_rate']} revenue={x['revenue']} collected={x['collected']} updated={x.get('updated_at','')[:10]}")

# 3) 從 consultation_cases 重新計算這三位 115/01-03 應有的月度統計
print("\n[3] 從 consultation_cases 實際計算出的 115/01-03 月度數字")
for name, lid in TARGET_IDS.items():
    r = httpx.get(f"{url}/rest/v1/consultation_cases",
                  params={
                      "select": "case_date,is_signed,revenue,collected",
                      "lawyer_id": f"eq.{lid}",
                      "case_date": "gte.2026-01-01",
                      "and": "(case_date.lte.2026-03-31)",
                      "limit": "500",
                  },
                  headers=headers)
    cases = r.json()
    buckets = {}
    for c in cases:
        m = c["case_date"][:7]  # '2026-01'
        b = buckets.setdefault(m, {"consult": 0, "signed": 0, "rev": 0, "col": 0})
        b["consult"] += 1
        if c["is_signed"]:
            b["signed"] += 1
        b["rev"] += c.get("revenue") or 0
        b["col"] += c.get("collected") or 0
    print(f"\n  === {name} ===")
    for m in sorted(buckets):
        b = buckets[m]
        rate = (b["signed"] / b["consult"] * 100) if b["consult"] else 0
        print(f"    {m}  consult={b['consult']:>3} signed={b['signed']:>3} "
              f"rate={rate:.1f}% revenue={b['rev']} collected={b['col']}")
