"""用 consultation_cases (17.8K rows, 由律師回填) 重做 sign rate decomposition"""
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

# probe consultation_cases schema first
print("=== consultation_cases sample ===")
sample = q_all("consultation_cases", {"select": "*", "limit": "3", "order": "case_date.desc"})
for r in sample[:3]:
    print(f"  {r}")
print()

# lawyers
lawyers = q_all("lawyers", {"select": "id,name"})
id_to_name = {l["id"]: l["name"] for l in lawyers}

# consultation_cases 2025 Jan-Apr + 2026 Jan-Apr
print("loading consultation_cases 2025-01-01 ~ 2026-04-30...")
cc = q_all("consultation_cases", {
    "select": "lawyer_id,case_date,is_signed,revenue,collected,case_type",
    "case_date": "gte.2025-01-01",
})
print(f"  {len(cc)} cases")

# revenue_records → lawyer→primary group mapping (2025)
print("loading revenue_records 2025 for lawyer→group mapping...")
rr = q_all("revenue_records", {
    "select": "record_date,group_name,responsible_lawyer,amount,transaction_type",
    "record_date": "gte.2025-01-01",
})
lawyer_group_rev = defaultdict(lambda: defaultdict(float))
for r in rr:
    if r.get("transaction_type") != "PaymentTransaction": continue
    if (r.get("record_date") or "") >= "2026-01": continue
    lw = r.get("responsible_lawyer")
    if not lw: continue
    g = r.get("group_name") or "(NULL)"
    lawyer_group_rev[lw][g] += float(r.get("amount") or 0)
lawyer_primary_group = {lw: max(grps.items(), key=lambda x:x[1])[0]
                         for lw, grps in lawyer_group_rev.items()}

TARGET_GROUPS = {"北所一部":"北一","北所二部":"北二","桃所一部":"桃一","中所一部":"中一",
                 "雄所一部":"雄一","南所一部":"南一","竹所一部":"竹一","北所四部":"北四"}

def classify(group):
    if not group: return "其他"
    if group in TARGET_GROUPS: return TARGET_GROUPS[group]
    if "北所合署" in group: return "北合署"
    if "中所合署" in group: return "中合署"
    return "其他"

def in_period(d, year):
    return d and d.startswith(f"{year}-") and d[5:7] in ("01","02","03","04")

# Per lawyer aggregation
per_lawyer = defaultdict(lambda: {"25_c":0, "25_s":0, "26_c":0, "26_s":0})
for c in cc:
    lid = c.get("lawyer_id")
    if not lid: continue
    d = c.get("case_date")
    is_signed = c.get("is_signed")
    if in_period(d, 2025):
        per_lawyer[lid]["25_c"] += 1
        if is_signed: per_lawyer[lid]["25_s"] += 1
    elif in_period(d, 2026):
        per_lawyer[lid]["26_c"] += 1
        if is_signed: per_lawyer[lid]["26_s"] += 1

# Aggregate by group bucket × cohort
print("\n=== Jan-Apr 同期 sign rate decomposition (consultation_cases) ===")
print(f"{'group':<10} {'cohort':<12} {'律師數':>5} {'25諮詢':>7} {'25成案':>7} {'25率':>6} {'26諮詢':>7} {'26成案':>7} {'26率':>6} {'Δppt':>6}")

buckets = ["北一","北二","桃一","中一","雄一","南一","竹一","北四","北合署","中合署"]

# Track 集團 total
TOTAL = {"留任": {"25_c":0,"25_s":0,"26_c":0,"26_s":0},
         "新進(26)": {"25_c":0,"25_s":0,"26_c":0,"26_s":0},
         "離開(25)": {"25_c":0,"25_s":0,"26_c":0,"26_s":0}}

for g in buckets:
    lawyers_in = [lid for lid in per_lawyer
                  if classify(lawyer_primary_group.get(id_to_name.get(lid,""), None)) == g]
    for cohort in ["留任", "新進(26)", "離開(25)"]:
        c25c=s25s=c26c=c26s = 0
        nlw = 0
        for lid in lawyers_in:
            d = per_lawyer[lid]
            in25 = d["25_c"] > 0
            in26 = d["26_c"] > 0
            if cohort == "留任" and not (in25 and in26): continue
            if cohort == "新進(26)" and not (in26 and not in25): continue
            if cohort == "離開(25)" and not (in25 and not in26): continue
            nlw += 1
            c25c += d["25_c"]; s25s += d["25_s"]
            c26c += d["26_c"]; c26s += d["26_s"]
        if nlw == 0: continue
        r25 = (s25s/c25c*100) if c25c else 0
        r26 = (c26s/c26c*100) if c26c else 0
        delta = r26 - r25 if (c25c and c26c) else 0
        print(f"{g:<10} {cohort:<12} {nlw:>5} {c25c:>7} {s25s:>7} {r25:>5.1f}% {c26c:>7} {c26s:>7} {r26:>5.1f}% {delta:>+5.1f}")
        TOTAL[cohort]["25_c"] += c25c; TOTAL[cohort]["25_s"] += s25s
        TOTAL[cohort]["26_c"] += c26c; TOTAL[cohort]["26_s"] += c26s

# Total decomposition
print("\n=== 集團 (北一+北二+桃一+中一+雄一+南一+竹一+北四+合署) 全 cohort decomposition ===")
print(f"{'cohort':<12} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>6}")
for cohort, d in TOTAL.items():
    r25 = (d["25_s"]/d["25_c"]*100) if d["25_c"] else 0
    r26 = (d["26_s"]/d["26_c"]*100) if d["26_c"] else 0
    delta = r26 - r25 if (d["25_c"] and d["26_c"]) else 0
    print(f"{cohort:<12} {d['25_c']:>7} {r25:>5.1f}% {d['26_c']:>7} {r26:>5.1f}% {delta:>+5.1f}")

# Mix shift decomposition: 集團 sign rate = weighted by cohort
TOT_25 = sum(d["25_c"] for d in TOTAL.values())
TOT_26 = sum(d["26_c"] for d in TOTAL.values())
TOT_25_S = sum(d["25_s"] for d in TOTAL.values())
TOT_26_S = sum(d["26_s"] for d in TOTAL.values())
print(f"\n集團 2025 同期: {TOT_25_S}/{TOT_25} = {TOT_25_S/TOT_25*100:.1f}%")
print(f"集團 2026 同期: {TOT_26_S}/{TOT_26} = {TOT_26_S/TOT_26*100:.1f}%")

# Counterfactual: 假設留任律師 sign rate 沒掉，集團今年會怎樣？
ret = TOTAL["留任"]
ret_r25 = ret["25_s"]/ret["25_c"]*100 if ret["25_c"] else 0
# Counterfactual 留任 26 諮詢量 × 25 率 + 新進(26) 26 諮詢量 × 新進實際率
new = TOTAL["新進(26)"]
new_r26 = (new["26_s"]/new["26_c"]*100) if new["26_c"] else 0
cf_signed = ret["26_c"] * ret_r25/100 + new["26_c"] * new_r26/100
cf_rate = cf_signed / (ret["26_c"] + new["26_c"]) * 100
print(f"\nCounterfactual (留任律師 26 率不掉，新進保持實際率):")
print(f"  集團 26 應該是: {cf_rate:.1f}%")
print(f"  實際 26 是:    {TOT_26_S/TOT_26*100:.1f}%")
print(f"  → 退化來自留任律師的部分: {cf_rate - TOT_26_S/TOT_26*100:+.1f}ppt")

# 北一 individual ranking
print("\n=== 北一律師 個人 sign rate YoY (留任 + 諮詢量≥15) ===")
beiyi = [lid for lid in per_lawyer
         if classify(lawyer_primary_group.get(id_to_name.get(lid,""), None)) == "北一"]
rows_out = []
for lid in beiyi:
    d = per_lawyer[lid]
    if d["25_c"] < 15 or d["26_c"] < 15: continue
    r25 = d["25_s"]/d["25_c"]*100
    r26 = d["26_s"]/d["26_c"]*100
    rows_out.append((id_to_name.get(lid,"?"), d["25_c"], r25, d["26_c"], r26, r26-r25))
rows_out.sort(key=lambda x: x[5])
print(f"{'律師':<10} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for name, c25, r25, c26, r26, dt in rows_out:
    print(f"{name:<10} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {dt:>+6.1f}")

# 集團整體律師（諮詢量≥30）
print("\n=== 集團 top decline 律師 (留任 + 25諮詢量≥30) ===")
all_rows = []
for lid in per_lawyer:
    d = per_lawyer[lid]
    if d["25_c"] < 30 or d["26_c"] < 10: continue
    r25 = d["25_s"]/d["25_c"]*100
    r26 = d["26_s"]/d["26_c"]*100
    name = id_to_name.get(lid, "?")
    group = classify(lawyer_primary_group.get(name, None))
    all_rows.append((name, group, d["25_c"], r25, d["26_c"], r26, r26-r25))
all_rows.sort(key=lambda x: x[6])
print(f"{'律師':<10} {'所':<6} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for name, g, c25, r25, c26, r26, dt in all_rows[:20]:
    print(f"{name:<10} {g:<6} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {dt:>+6.1f}")
