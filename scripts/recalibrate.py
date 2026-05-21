"""重撈：全 fetch + client-side aggregation，避開 server-side filter bug"""
import sys, io, urllib.request, urllib.parse, json
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "https://zpbkeyhxyykbvownrngf.supabase.co"
import os; KEY = os.environ["SUPABASE_SERVICE_KEY"]

def q_all(path, params, page=1000):
    out, offset = [], 0
    while True:
        p = dict(params); p["limit"]=str(page); p["offset"]=str(offset)
        url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
        chunk = json.loads(urllib.request.urlopen(req).read())
        out.extend(chunk)
        if len(chunk) < page: break
        offset += page
    return out

print("fetching all revenue_records 2025-01-01 ~ ...")
rows = q_all("revenue_records", {
    "select": "record_date,group_name,amount,transaction_type,office",
    "record_date": "gte.2025-01-01",
    "order": "record_date.asc",  # consistent ordering for pagination
})
print(f"  loaded {len(rows)} rows\n")

# monthly × group_name
mon_grp = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # [pay, ref]
for r in rows:
    m = (r.get("record_date") or "")[:7]
    g = r.get("group_name") or "(NULL)"
    a = float(r.get("amount") or 0)
    if r.get("transaction_type") == "PaymentTransaction":
        mon_grp[m][g][0] += a
    else:
        mon_grp[m][g][1] += abs(a)

def period(m):
    if not m: return None
    if m < "2026-01": return "2025"
    if m < "2026-05": return "2026YTD"
    return "later"

# Aggregate per group × period
agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for m, gd in mon_grp.items():
    p = period(m)
    if not p: continue
    for g, (pay, ref) in gd.items():
        agg[g][p][0] += pay
        agg[g][p][1] += ref

print("=== 重撈：2025 vs 2026YTD by group_name ===")
print(f"{'group_name':<35} {'2025 rev':>10} {'2025 ref%':>9} {'26YTD rev':>10} {'26ann':>8} {'YoY%':>7}")
for g in sorted(agg, key=lambda x: -agg[x]["2025"][0]):
    d25 = agg[g]["2025"]
    d26 = agg[g]["2026YTD"]
    if d25[0] < 5_000_000 and d26[0] < 2_000_000: continue
    rev25 = d25[0]/10000
    ref25_pct = d25[1]/d25[0]*100 if d25[0] else 0
    rev26 = d26[0]/10000
    ann = rev26 * 3
    yoy = (ann/rev25 - 1)*100 if rev25 else 0
    print(f"{g[:33]:<35} {rev25:>10.0f} {ref25_pct:>8.1f}% {rev26:>10.0f} {ann:>8.0f} {yoy:>+6.1f}%")

# 北一月度 sanity
print("\n=== 北所一部 月度 sanity check ===")
for m in sorted(mon_grp):
    if m > "2026-06": continue
    pay, ref = mon_grp[m].get("北所一部", [0,0])
    if pay > 0 or ref > 0:
        print(f"  {m}: 收 {pay/10000:>7.1f} 萬  退 {ref/10000:>5.1f} 萬")

print("\n=== 北所二部 月度 sanity check ===")
for m in sorted(mon_grp):
    if m > "2026-06": continue
    pay, ref = mon_grp[m].get("北所二部", [0,0])
    if pay > 0 or ref > 0:
        print(f"  {m}: 收 {pay/10000:>7.1f} 萬  退 {ref/10000:>5.1f} 萬")
