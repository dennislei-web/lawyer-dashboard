"""Show pure phantom rows in monthly_stats (rows with no matching consultation_cases)."""
import httpx, os, io, sys
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

def get_all(path, **params):
    rows = []
    for offset in range(0, 50000, 1000):
        h = {**H, "Range-Unit": "items", "Range": f"{offset}-{offset+999}"}
        r = httpx.get(f"{URL}/rest/v1/{path}", params=params, headers=h, timeout=60)
        r.raise_for_status()
        b = r.json()
        if not b: break
        rows.extend(b)
        if len(b) < 1000: break
    return rows

cases = get_all("consultation_cases", select="lawyer_id,case_date")
case_keys = set()
for c in cases:
    if c.get("case_date") and c.get("lawyer_id"):
        case_keys.add((c["lawyer_id"], c["case_date"][:7]))

ms = get_all("monthly_stats", select="lawyer_id,month,consult_count,signed_count,revenue,collected")
lawyers = httpx.get(f"{URL}/rest/v1/lawyers", params={"select": "id,name"}, headers=H, timeout=30).json()
names = {l["id"]: l["name"] for l in lawyers}

phantoms = [m for m in ms if (m["lawyer_id"], m["month"]) not in case_keys]
print(f"Pure phantoms: {len(phantoms)} 筆\n")
print(f"{'lawyer':<10}{'month':<10}{'consult':<10}{'signed':<10}{'revenue':<14}{'collected':<14}")
for p in sorted(phantoms, key=lambda x: (-x['collected'], x['month'])):
    name = names.get(p['lawyer_id'], '?')
    # pad by character count, not byte count
    padded = name + " " * (10 - len(name))
    print(f"{padded}{p['month']:<10}{p['consult_count']:<10}{p['signed_count']:<10}${p['revenue']:>10,}    ${p['collected']:>10,}")
print(f"\n合計 collected: ${sum(p['collected'] for p in phantoms):,}")
