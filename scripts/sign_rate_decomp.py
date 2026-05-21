"""
判別 sign rate 集團性下降的根因：
  - 同律師 YoY 比較（同 Jan-Apr 期間）
  - 新進律師稀釋 vs 留任律師退化
  - 按 group_name 拆 (北一/北合署/桃一/中一)
"""
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

# 1. lawyers id->name
print("loading lawyers...")
lawyers = q_all("lawyers", {"select": "id,name,is_active,office"})
id_to_name = {l["id"]: l["name"] for l in lawyers}
print(f"  {len(lawyers)} lawyers")

# 2. monthly_stats 2025-01 ~ 2026-05
print("loading monthly_stats...")
ms = q_all("monthly_stats", {"select": "lawyer_id,month,consult_count,signed_count,revenue,collected",
                              "month": "gte.2025-01"})
print(f"  {len(ms)} stat rows")

# 3. revenue_records 2025 全年 → derive lawyer→primary group_name
print("loading revenue_records for lawyer→group mapping...")
rr = q_all("revenue_records", {"select": "record_date,group_name,responsible_lawyer,amount,transaction_type",
                                "record_date": "gte.2025-01-01"})
print(f"  {len(rr)} revenue rows")

# 律師→其主要 group (by 2025 total responsible_lawyer revenue)
lawyer_group_rev = defaultdict(lambda: defaultdict(float))
for r in rr:
    if r.get("transaction_type") != "PaymentTransaction": continue
    if (r.get("record_date") or "") >= "2026-01": continue
    lw = r.get("responsible_lawyer")
    if not lw: continue
    g = r.get("group_name") or "(NULL)"
    lawyer_group_rev[lw][g] += float(r.get("amount") or 0)

lawyer_primary_group = {}
for lw, grps in lawyer_group_rev.items():
    primary = max(grps.items(), key=lambda x: x[1])[0]
    lawyer_primary_group[lw] = primary

# Buckets to analyze
TARGET_GROUPS = {
    "北所一部": "北一",
    "北所二部": "北二",
    "桃所一部": "桃一",
    "中所一部": "中一",
    "雄所一部": "雄一",
    "南所一部": "南一",
    "竹所一部": "竹一",
}
COHORT_GROUPS = ["北所合署", "中所合署"]

def classify(group):
    if not group: return "(無)"
    if group in TARGET_GROUPS: return TARGET_GROUPS[group]
    for c in COHORT_GROUPS:
        if c in group: return "合署cohort"
    return "其他"

# Aggregate monthly_stats per lawyer for 2025 Jan-Apr vs 2026 Jan-Apr
def in_period(m, year):
    return m.startswith(f"{year}-") and m[5:7] in ("01","02","03","04")

per_lawyer = defaultdict(lambda: {"25_c":0, "25_s":0, "26_c":0, "26_s":0})
for s in ms:
    lid = s["lawyer_id"]
    m = s["month"]
    c = s.get("consult_count") or 0
    sg = s.get("signed_count") or 0
    if in_period(m, 2025):
        per_lawyer[lid]["25_c"] += c
        per_lawyer[lid]["25_s"] += sg
    elif in_period(m, 2026):
        per_lawyer[lid]["26_c"] += c
        per_lawyer[lid]["26_s"] += sg

# 4. Decomposition by group bucket
print("\n=== Jan-Apr same-period sign rate decomposition ===")
print(f"{'group':<10} {'cohort':<12} {'律師數':>6} {'25諮詢':>7} {'25成案':>7} {'25率':>6} {'26諮詢':>7} {'26成案':>7} {'26率':>6} {'Δppt':>6}")

groups_buckets = ["北一","北二","桃一","中一","雄一","南一","竹一","合署cohort"]

for g in groups_buckets:
    # Find lawyers whose primary group maps to this bucket
    lawyers_in = [lid for lid in per_lawyer
                  if classify(lawyer_primary_group.get(id_to_name.get(lid,""), None)) == g]

    for cohort_type in ["留任", "新進(26)", "離開(25)"]:
        c25c=s25s=c26c=c26s = 0
        nlw = 0
        for lid in lawyers_in:
            d = per_lawyer[lid]
            in_25 = d["25_c"] > 0
            in_26 = d["26_c"] > 0
            if cohort_type == "留任" and not (in_25 and in_26): continue
            if cohort_type == "新進(26)" and not (in_26 and not in_25): continue
            if cohort_type == "離開(25)" and not (in_25 and not in_26): continue
            nlw += 1
            c25c += d["25_c"]; s25s += d["25_s"]
            c26c += d["26_c"]; c26s += d["26_s"]
        if nlw == 0: continue
        r25 = (s25s/c25c*100) if c25c else 0
        r26 = (c26s/c26c*100) if c26c else 0
        delta = r26 - r25 if (c25c and c26c) else 0
        print(f"{g:<10} {cohort_type:<12} {nlw:>6} {c25c:>7} {s25s:>7} {r25:>5.1f}% {c26c:>7} {c26s:>7} {r26:>5.1f}% {delta:>+5.1f}")

# 5. 北一律師 individual ranking — same lawyer 2025 vs 2026 sign rate
print("\n=== 北一律師 個人 sign rate YoY (only 留任 + 諮詢量≥10) ===")
beiyi_lawyers = [lid for lid in per_lawyer
                 if classify(lawyer_primary_group.get(id_to_name.get(lid,""), None)) == "北一"]
rows_out = []
for lid in beiyi_lawyers:
    d = per_lawyer[lid]
    if d["25_c"] < 10 or d["26_c"] < 10: continue
    r25 = d["25_s"]/d["25_c"]*100
    r26 = d["26_s"]/d["26_c"]*100
    rows_out.append((id_to_name.get(lid,"?"), d["25_c"], r25, d["26_c"], r26, r26-r25))
rows_out.sort(key=lambda x: x[5])  # ascending = biggest drop first
print(f"{'律師':<10} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for name, c25, r25, c26, r26, d in rows_out:
    print(f"{name:<10} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {d:>+6.1f}")

# 6. 合署 cohort 個別律師
print("\n=== 北所合署 cohort 個人 sign rate YoY (留任 + 諮詢量≥5) ===")
hsh_lawyers = [lid for lid in per_lawyer
               if "北所合署" in (lawyer_primary_group.get(id_to_name.get(lid,""), "") or "")]
rows_out = []
for lid in hsh_lawyers:
    d = per_lawyer[lid]
    if d["25_c"] < 5: continue
    r25 = d["25_s"]/d["25_c"]*100 if d["25_c"] else 0
    r26 = d["26_s"]/d["26_c"]*100 if d["26_c"] else 0
    delta = r26-r25 if d["26_c"] >= 5 else None
    rows_out.append((id_to_name.get(lid,"?"), d["25_c"], r25, d["26_c"], r26, delta))
rows_out.sort(key=lambda x: x[5] if x[5] is not None else 999)
print(f"{'律師':<10} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for name, c25, r25, c26, r26, dlt in rows_out:
    d_str = f"{dlt:+.1f}" if dlt is not None else "N/A"
    print(f"{name:<10} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {d_str:>7}")
