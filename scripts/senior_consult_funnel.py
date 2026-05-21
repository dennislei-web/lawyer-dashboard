"""
純諮詢律師（無→無 senior funnel）10 位 deep dive
- 個別 sign rate trend Jan-Apr 25 vs 26
- 月度 trajectory
- 案型 mix
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

# lawyers
lawyers = q_all("lawyers", {"select": "id,name,is_active,role,office"})
id_to_name = {l["id"]: l["name"] for l in lawyers}
name_to = {l["name"]: l for l in lawyers}

# revenue_records → 律師 × period 出現的 group
print("loading revenue_records...")
rr = q_all("revenue_records", {
    "select": "record_date,group_name,responsible_lawyer,transaction_type,amount",
    "record_date": "gte.2025-01-01",
})
def period(d):
    if not d: return None
    if d.startswith("2025") and d[5:7] in ("01","02","03","04"): return "25H1"
    if d.startswith("2025"): return "25other"
    if d.startswith("2026") and d[5:7] in ("01","02","03","04"): return "26H1"
    return None

lawyer_groups = defaultdict(set)  # name -> set of group_name observed across all periods
for r in rr:
    if r.get("transaction_type") != "PaymentTransaction": continue
    lw = r.get("responsible_lawyer")
    g = r.get("group_name")
    if lw and g: lawyer_groups[lw].add(g)

# consultation_cases
print("loading consultation_cases 2025-01 ~ 2026-05...")
cc = q_all("consultation_cases", {
    "select": "lawyer_id,case_date,is_signed,case_type,revenue,collected",
})

def cc_period(d):
    if not d: return None
    if d.startswith("2025") and d[5:7] in ("01","02","03","04"): return "25H1"
    if d.startswith("2026") and d[5:7] in ("01","02","03","04"): return "26H1"
    return None

# 找出純諮詢律師：在 cc 有 case 但 never 作為 responsible_lawyer 在 revenue_records
cc_lawyer_names = set()
for c in cc:
    n = id_to_name.get(c.get("lawyer_id"))
    if n: cc_lawyer_names.add(n)

pure_consult = []
for n in cc_lawyer_names:
    if n not in lawyer_groups:  # 沒在 revenue_records 出現作為主辦
        pure_consult.append(n)

print(f"\n=== 純諮詢律師 (cc 有資料但 revenue_records 無 responsible_lawyer): {len(pure_consult)} 位 ===")

# 每位 25H1 vs 26H1
per_lawyer = defaultdict(lambda: {"25H1_c":0,"25H1_s":0,"26H1_c":0,"26H1_s":0})
per_lawyer_mon = defaultdict(lambda: defaultdict(lambda: [0,0]))  # name -> month -> [c, s]
for c in cc:
    name = id_to_name.get(c.get("lawyer_id"))
    if not name: continue
    d = c.get("case_date")
    if not d: continue
    p = cc_period(d)
    if p:
        per_lawyer[name][f"{p}_c"] += 1
        if c.get("is_signed"): per_lawyer[name][f"{p}_s"] += 1
    m = d[:7]
    per_lawyer_mon[name][m][0] += 1
    if c.get("is_signed"): per_lawyer_mon[name][m][1] += 1

print(f"\n{'律師':<10} {'role':<10} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'量Δ%':>7} {'率Δppt':>7}")
rows = []
for n in pure_consult:
    d = per_lawyer[n]
    if d["25H1_c"] < 5 and d["26H1_c"] < 5: continue
    r25 = d["25H1_s"]/d["25H1_c"]*100 if d["25H1_c"] else 0
    r26 = d["26H1_s"]/d["26H1_c"]*100 if d["26H1_c"] else 0
    vol_pct = (d["26H1_c"]/d["25H1_c"]-1)*100 if d["25H1_c"] else 999
    dlt = r26-r25 if (d["25H1_c"] and d["26H1_c"]) else None
    role = name_to.get(n,{}).get("role","?")
    rows.append((n, role, d["25H1_c"], r25, d["26H1_c"], r26, vol_pct, dlt))
rows.sort(key=lambda x: (x[7] if x[7] is not None else 999))
for n, role, c25, r25, c26, r26, vp, dt in rows:
    d_s = f"{dt:+.1f}" if dt is not None else "N/A"
    vp_s = f"{vp:+.0f}%"
    print(f"{n:<10} {role:<10} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {vp_s:>7} {d_s:>7}")

# 月度 trajectory for each
print("\n=== 個別月度 trajectory（諮詢量 / sign rate）===")
for n in pure_consult:
    d = per_lawyer[n]
    if d["25H1_c"] < 10 and d["26H1_c"] < 10: continue
    print(f"\n--- {n} ({name_to.get(n,{}).get('role','?')}) ---")
    mons = sorted(per_lawyer_mon[n])
    for m in mons:
        c, s = per_lawyer_mon[n][m]
        if c == 0: continue
        rate = s/c*100
        bar = "█" * int(rate/5)
        print(f"  {m}: {c:>3} 諮詢 {s:>2} 簽 {rate:>5.1f}% {bar}")

# 案型分布
print("\n=== 純諮詢律師 案型 mix (25H1 vs 26H1) ===")
for n in [r[0] for r in rows[:6]]:  # top 6 by row count
    d = per_lawyer[n]
    if d["25H1_c"] < 15 or d["26H1_c"] < 10: continue
    print(f"\n--- {n} ---")
    case_types_25 = defaultdict(lambda: [0,0])
    case_types_26 = defaultdict(lambda: [0,0])
    for c in cc:
        name = id_to_name.get(c.get("lawyer_id"))
        if name != n: continue
        ct = c.get("case_type") or "(無)"
        p = cc_period(c.get("case_date"))
        if p == "25H1":
            case_types_25[ct][0] += 1
            if c.get("is_signed"): case_types_25[ct][1] += 1
        elif p == "26H1":
            case_types_26[ct][0] += 1
            if c.get("is_signed"): case_types_26[ct][1] += 1
    all_types = set(case_types_25) | set(case_types_26)
    print(f"  {'案型':<12} {'25 n':>5} {'25 率':>6} {'26 n':>5} {'26 率':>6}")
    for ct in sorted(all_types, key=lambda x: -(case_types_25[x][0]+case_types_26[x][0])):
        c25 = case_types_25[ct]; c26 = case_types_26[ct]
        if c25[0]+c26[0] < 3: continue
        r25 = c25[1]/c25[0]*100 if c25[0] else 0
        r26 = c26[1]/c26[0]*100 if c26[0] else 0
        print(f"  {ct:<12} {c25[0]:>5} {r25:>5.0f}% {c26[0]:>5} {r26:>5.0f}%")
