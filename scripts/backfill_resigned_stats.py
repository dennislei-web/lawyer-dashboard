"""
從 consultation_cases 補建離職律師的 monthly_stats
將每位離職律師的案件按月彙總，產生 monthly_stats 記錄
"""
import os, io, sys, json
import httpx
from dotenv import load_dotenv
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}
write_headers = {**headers, "Content-Type": "application/json", "Prefer": "return=representation"}

# 1. 取得所有離職律師
resp = httpx.get(f"{url}/rest/v1/lawyers", params={
    "select": "id,name",
    "is_active": "eq.false",
}, headers=headers)
resigned = resp.json()
print(f"離職律師共 {len(resigned)} 位")

if not resigned:
    print("無離職律師，結束")
    sys.exit(0)

resigned_ids = {l["id"]: l["name"] for l in resigned}

# 2. 取得所有離職律師的 consultation_cases（用 service key 繞過 RLS）
all_cases = []
for lawyer_id, name in resigned_ids.items():
    offset = 0
    page_size = 1000
    while True:
        resp = httpx.get(f"{url}/rest/v1/consultation_cases", params={
            "select": "lawyer_id,case_date,is_signed,revenue,collected",
            "lawyer_id": f"eq.{lawyer_id}",
            "order": "case_date",
            "offset": str(offset),
            "limit": str(page_size),
        }, headers=headers)
        page = resp.json()
        if not page:
            break
        all_cases.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

print(f"共取得 {len(all_cases)} 筆離職律師案件")

if not all_cases:
    print("離職律師沒有案件資料，結束")
    sys.exit(0)

# 3. 按 (lawyer_id, month) 彙總
monthly = defaultdict(lambda: {
    "consult_count": 0,
    "signed_count": 0,
    "revenue": 0,
    "collected": 0,
})

for c in all_cases:
    if not c.get("case_date"):
        continue
    # case_date 格式: "2025-03-15" 或 "2025-03"
    month = c["case_date"][:7]  # "2025-03"
    key_tuple = (c["lawyer_id"], month)
    monthly[key_tuple]["consult_count"] += 1
    if c.get("is_signed"):
        monthly[key_tuple]["signed_count"] += 1
    monthly[key_tuple]["revenue"] += int(c.get("revenue") or 0)
    monthly[key_tuple]["collected"] += int(c.get("collected") or 0)

print(f"彙總出 {len(monthly)} 筆月統計")

# 4. 組裝 upsert 資料
rows = []
for (lawyer_id, month), stats in monthly.items():
    consult = stats["consult_count"]
    signed = stats["signed_count"]
    sign_rate = round(signed / consult * 100, 2) if consult > 0 else 0
    rows.append({
        "lawyer_id": lawyer_id,
        "month": month,
        "consult_count": consult,
        "signed_count": signed,
        "sign_rate": sign_rate,
        "revenue": stats["revenue"],
        "collected": stats["collected"],
    })

# 5. 批次 upsert（每次 200 筆）
batch_size = 200
total_upserted = 0
for i in range(0, len(rows), batch_size):
    batch = rows[i:i+batch_size]
    resp = httpx.post(
        f"{url}/rest/v1/monthly_stats?on_conflict=lawyer_id,month",
        json=batch,
        headers={**write_headers, "Prefer": "resolution=merge-duplicates,return=representation"},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        total_upserted += len(resp.json())
    else:
        print(f"✗ 批次 {i//batch_size+1} 失敗: {resp.status_code} {resp.text}")

print(f"\n✓ 成功 upsert {total_upserted} 筆 monthly_stats")

# 6. 顯示每位離職律師的統計摘要
print("\n=== 離職律師統計摘要 ===")
lawyer_summary = defaultdict(lambda: {"consult": 0, "signed": 0, "collected": 0, "months": 0})
for (lawyer_id, month), stats in monthly.items():
    s = lawyer_summary[lawyer_id]
    s["consult"] += stats["consult_count"]
    s["signed"] += stats["signed_count"]
    s["collected"] += stats["collected"]
    s["months"] += 1

for lawyer_id, s in sorted(lawyer_summary.items(), key=lambda x: x[1]["collected"], reverse=True):
    name = resigned_ids.get(lawyer_id, "?")
    eff = s["collected"] / s["consult"] if s["consult"] > 0 else 0
    rate = s["signed"] / s["consult"] * 100 if s["consult"] > 0 else 0
    print(f"  {name}: {s['months']}個月 | 諮詢{s['consult']} | 成案{s['signed']} | 成案率{rate:.1f}% | 已收${s['collected']:,} | 效益${eff:,.0f}")
