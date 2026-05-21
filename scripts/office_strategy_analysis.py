"""
各所經營策略分析 — 2026 戰略 thread #3
拉 revenue × office × group_name + 退款率 + 案型分布
"""
import sys, io, urllib.request, urllib.parse, json
from collections import defaultdict, Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "https://zpbkeyhxyykbvownrngf.supabase.co"
import os; KEY = os.environ["SUPABASE_SERVICE_KEY"]

def q(path, params):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}"
    })
    return json.loads(urllib.request.urlopen(req).read())

def q_all(path, params, page=1000):
    out, offset = [], 0
    while True:
        p = dict(params); p["limit"]=str(page); p["offset"]=str(offset)
        chunk = q(path, p)
        out.extend(chunk)
        if len(chunk) < page: break
        offset += page
    return out

# 拉 2025 全年 + 2026 YTD revenue_records
print("loading revenue_records 2025-01-01 ~ 2026-12-31 ...")
rows = q_all("revenue_records", {
    "select": "record_date,office,group_name,source_channel,service_items,amount,transaction_type,responsible_lawyer,assigned_lawyers",
    "record_date": "gte.2025-01-01",
})
print(f"  loaded {len(rows)} rows\n")

def period(d):
    if not d: return None
    if d < "2026-01-01": return "2025"
    if d < "2026-05-01": return "2026YTD"  # Jan-Apr 4 months
    return "2026May+"

# 排除「北所合署」收件人為合署的（合署本身不算所內）
# 我們要的是「所內 vs 合署」對比，所以 group_name 同時揭露
# 1) by group_name × period
agg = defaultdict(lambda: {"revenue":0, "refund":0, "n_pay":0, "n_ref":0})
for r in rows:
    p = period(r.get("record_date"))
    if p not in ("2025", "2026YTD"): continue
    g = r.get("group_name") or "(無)"
    amt = float(r.get("amount") or 0)
    tt = r.get("transaction_type")
    k = (g, p)
    if tt == "PaymentTransaction":
        agg[k]["revenue"] += amt
        agg[k]["n_pay"] += 1
    elif tt == "RefundTransaction":
        agg[k]["refund"] += abs(amt)
        agg[k]["n_ref"] += 1

# print group_name summary
print("=== revenue / refund by group_name (2025 vs 2026 YTD Jan-Apr) ===")
print(f"{'group_name':<32} {'period':<10} {'rev(萬)':>10} {'ref(萬)':>10} {'ref%':>7} {'n_pay':>7} {'n_ref':>7}")
groups = sorted(set(k[0] for k in agg.keys()))
for g in groups:
    for p in ("2025", "2026YTD"):
        d = agg.get((g, p))
        if not d or d["revenue"] < 100000: continue
        rev_w = d["revenue"]/10000
        ref_w = d["refund"]/10000
        pct = (d["refund"] / d["revenue"] * 100) if d["revenue"] else 0
        print(f"{g[:30]:<32} {p:<10} {rev_w:>10.1f} {ref_w:>10.1f} {pct:>6.1f}% {d['n_pay']:>7} {d['n_ref']:>7}")

# 2) annualize 2026 YTD for direct compare
print("\n=== 2026 年化 (YTD ×3) vs 2025 比較 ===")
print(f"{'group_name':<32} {'2025 rev':>10} {'26 年化':>10} {'YoY%':>7} {'25 ref%':>8} {'26 ref%':>8}")
for g in groups:
    d25 = agg.get((g, "2025"))
    d26 = agg.get((g, "2026YTD"))
    if not d25 or d25["revenue"] < 1000000: continue
    rev25 = d25["revenue"]/10000
    rev26 = (d26["revenue"]/10000)*3 if d26 else 0
    yoy = (rev26/rev25 - 1)*100 if rev25 else 0
    ref25_pct = (d25["refund"]/d25["revenue"]*100) if d25["revenue"] else 0
    ref26_pct = (d26["refund"]/d26["revenue"]*100) if d26 and d26["revenue"] else 0
    print(f"{g[:30]:<32} {rev25:>10.0f} {rev26:>10.0f} {yoy:>+6.1f}% {ref25_pct:>7.1f}% {ref26_pct:>7.1f}%")

# 3) service_items distribution by 所 (2025)
print("\n=== 2025 案型分布 by 所內 group_name (top 8 group × top 8 service_items) ===")
si_by_group = defaultdict(lambda: defaultdict(float))
for r in rows:
    if period(r.get("record_date")) != "2025": continue
    if r.get("transaction_type") != "PaymentTransaction": continue
    g = r.get("group_name") or "(無)"
    if "合署" in g or "法顧" in g: continue  # 只看所內
    si = r.get("service_items") or "(無)"
    si_by_group[g][si] += float(r.get("amount") or 0)

top_groups = sorted(si_by_group.items(), key=lambda x: -sum(x[1].values()))[:8]
for g, items in top_groups:
    total = sum(items.values())
    print(f"\n  --- {g} (2025 total: {total/10000:.0f} 萬) ---")
    top_items = sorted(items.items(), key=lambda x: -x[1])[:8]
    for si, amt in top_items:
        print(f"     {si[:40]:<42} {amt/10000:>7.1f} 萬  ({amt/total*100:>4.1f}%)")

# 4) per-group responsible_lawyer headcount (rev/FTE proxy)
print("\n=== 2025 各 group 律師人數（responsible_lawyer distinct）+ rev/律師 ===")
lawyers_by_group = defaultdict(set)
for r in rows:
    if period(r.get("record_date")) != "2025": continue
    if r.get("transaction_type") != "PaymentTransaction": continue
    g = r.get("group_name") or "(無)"
    lw = r.get("responsible_lawyer")
    if lw: lawyers_by_group[g].add(lw)

for g in groups:
    d25 = agg.get((g, "2025"))
    if not d25 or d25["revenue"] < 1000000: continue
    if "合署" in g or "法顧" in g: continue
    n_lw = len(lawyers_by_group[g])
    rev_per = d25["revenue"]/10000/n_lw if n_lw else 0
    print(f"  {g:<32} 律師 {n_lw:>2} 人  rev/律師 {rev_per:>5.0f} 萬")
