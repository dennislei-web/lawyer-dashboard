"""
v3: 用 group_name 出現作為「合署身份」判定，而非 lawyers.is_active
- 律師在某 period 的身份 = 該期間其案件 revenue 主要落在哪個 group_name
- 「真離職」= is_active=False 且 兩個 period 都沒出現在合署 cohort group
- 「轉合署」= 2025 所內、2026 進合署 group
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

print("loading lawyers...")
lawyers = q_all("lawyers", {"select": "id,name,is_active"})
id_to_name = {l["id"]: l["name"] for l in lawyers}
name_to_active = {l["name"]: l.get("is_active", True) for l in lawyers}

print("loading revenue_records 2025-...")
rr = q_all("revenue_records", {
    "select": "record_date,group_name,responsible_lawyer,amount,transaction_type",
    "record_date": "gte.2025-01-01",
})

# 律師 × 期間 → group_name 分布
def period(d):
    if not d: return None
    if d.startswith("2025"): return "2025"
    if d.startswith("2026") and d[5:7] in ("01","02","03","04"): return "2026"
    return None

lawyer_period_group = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
for r in rr:
    if r.get("transaction_type") != "PaymentTransaction": continue
    p = period(r.get("record_date"))
    if not p: continue
    lw = r.get("responsible_lawyer")
    if not lw: continue
    g = r.get("group_name") or "(NULL)"
    lawyer_period_group[lw][p][g] += float(r.get("amount") or 0)

def primary_group_in_period(name, p):
    grps = lawyer_period_group.get(name, {}).get(p)
    if not grps: return None
    return max(grps.items(), key=lambda x: x[1])[0]

def identity(group):
    if not group: return None
    if "合署" in group: return "合署"
    if "法顧" in group: return "法顧"
    if group == "(NULL)": return None
    return "所內"  # 北一/北二/桃一/中一/...

# 對每位律師做 2 期 identity 判斷
print("\n=== 律師身份轉換矩陣 (2025 → 2026 同期Jan-Apr) ===")
transitions = defaultdict(list)
all_names = set(name_to_active.keys()) | set(lawyer_period_group.keys())
for n in all_names:
    g25 = primary_group_in_period(n, "2025")
    g26 = primary_period = primary_group_in_period(n, "2026")
    i25 = identity(g25)
    i26 = identity(g26)
    active = name_to_active.get(n, True)
    key = (i25 or "無", i26 or "無", "active" if active else "inactive")
    transitions[key].append(n)
print(f"{'25身份':<6} {'26身份':<6} {'active':<10} 人數  範例")
for (i25, i26, act), names in sorted(transitions.items(), key=lambda x: -len(x[1])):
    print(f"  {i25:<6} {i26:<6} {act:<10} {len(names):>3}  {', '.join(names[:6])}")

# 載入 consultation_cases
print("\nloading consultation_cases 2025-01 ~ 2026-04...")
cc = q_all("consultation_cases", {
    "select": "lawyer_id,case_date,is_signed",
})

# 律師 × period → consult, signed
def cc_period(d):
    if not d: return None
    if d.startswith("2025") and d[5:7] in ("01","02","03","04"): return "25H1"
    if d.startswith("2026") and d[5:7] in ("01","02","03","04"): return "26H1"
    return None

per_lawyer = defaultdict(lambda: {"25H1_c":0,"25H1_s":0,"26H1_c":0,"26H1_s":0})
for c in cc:
    lid = c.get("lawyer_id")
    if not lid: continue
    p = cc_period(c.get("case_date"))
    if not p: continue
    per_lawyer[lid][f"{p}_c"] += 1
    if c.get("is_signed"): per_lawyer[lid][f"{p}_s"] += 1

# 給每位律師分 cohort key
def classify(name):
    i25 = identity(primary_group_in_period(name, "2025"))
    i26 = identity(primary_group_in_period(name, "2026"))
    active = name_to_active.get(name, True)
    if i25 == "所內" and i26 == "所內": return "所內留任"
    if i25 == "合署" and i26 == "合署": return "合署留任"
    if i25 == "所內" and i26 == "合署": return "轉合署(2026)"
    if i25 == "合署" and i26 == "所內": return "回所內(2026)"
    if i25 == "所內" and i26 is None: return "所內離開(active)" if active else "所內離職"
    if i25 == "合署" and i26 is None: return "合署離開"
    if i25 is None and i26 == "所內": return "新進所內(2026)"
    if i25 is None and i26 == "合署": return "新進合署(2026)"
    return f"其他_{i25}_{i26}"

print("\n=== 集團 sign rate decomp by cohort transition ===")
agg = defaultdict(lambda: {"25c":0,"25s":0,"26c":0,"26s":0,"n":0})
for lid, d in per_lawyer.items():
    name = id_to_name.get(lid)
    if not name: continue
    cohort = classify(name)
    agg[cohort]["25c"] += d["25H1_c"]; agg[cohort]["25s"] += d["25H1_s"]
    agg[cohort]["26c"] += d["26H1_c"]; agg[cohort]["26s"] += d["26H1_s"]
    agg[cohort]["n"] += 1

print(f"{'cohort':<22} {'人':>4} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>6}")
order = ["所內留任","合署留任","轉合署(2026)","新進所內(2026)","新進合署(2026)",
         "所內離職","所內離開(active)","合署離開","其他_所內_None","其他_None_None"]
for c in order + [k for k in agg if k not in order]:
    if c not in agg: continue
    d = agg[c]
    if d["25c"] == 0 and d["26c"] == 0: continue
    r25 = d["25s"]/d["25c"]*100 if d["25c"] else 0
    r26 = d["26s"]/d["26c"]*100 if d["26c"] else 0
    delta = r26-r25 if (d["25c"] and d["26c"]) else 0
    print(f"{c:<22} {d['n']:>4} {d['25c']:>7} {r25:>5.1f}% {d['26c']:>7} {r26:>5.1f}% {delta:>+5.1f}")

# 過濾真離職後的集團 sign rate
print("\n=== 排除真離職後集團 sign rate ===")
inc = ["所內留任","合署留任","轉合署(2026)","新進所內(2026)","新進合署(2026)"]
tot = {"25c":0,"25s":0,"26c":0,"26s":0}
for c in inc:
    if c not in agg: continue
    for k in tot: tot[k] += agg[c][k]
r25 = tot["25s"]/tot["25c"]*100 if tot["25c"] else 0
r26 = tot["26s"]/tot["26c"]*100 if tot["26c"] else 0
print(f"  在編律師 25: {tot['25s']}/{tot['25c']} = {r25:.1f}%")
print(f"  在編律師 26: {tot['26s']}/{tot['26c']} = {r26:.1f}%")
print(f"  Δ = {r26-r25:+.1f}ppt")

# 轉合署律師的個別 trajectory
print("\n=== 轉合署(2026)律師個別 sign rate ===")
print(f"{'律師':<10} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for lid, d in per_lawyer.items():
    name = id_to_name.get(lid)
    if classify(name) != "轉合署(2026)": continue
    if d["25H1_c"] < 5 and d["26H1_c"] < 5: continue
    r25 = d["25H1_s"]/d["25H1_c"]*100 if d["25H1_c"] else 0
    r26 = d["26H1_s"]/d["26H1_c"]*100 if d["26H1_c"] else 0
    dlt = r26-r25 if (d["25H1_c"] and d["26H1_c"]) else None
    d_s = f"{dlt:+.1f}" if dlt is not None else "N/A"
    print(f"{name:<10} {d['25H1_c']:>7} {r25:>5.1f}% {d['26H1_c']:>7} {r26:>5.1f}% {d_s:>7}")

# 北合署 真留任律師（active 且 25/26 都合署）
print("\n=== 合署留任律師個別 sign rate (active only, 諮詢量≥10) ===")
rows_out = []
for lid, d in per_lawyer.items():
    name = id_to_name.get(lid)
    if classify(name) != "合署留任": continue
    if not name_to_active.get(name, True): continue
    if d["25H1_c"] < 10 or d["26H1_c"] < 10: continue
    r25 = d["25H1_s"]/d["25H1_c"]*100
    r26 = d["26H1_s"]/d["26H1_c"]*100
    g25 = primary_group_in_period(name, "2025") or ""
    rows_out.append((name, g25[:20], d["25H1_c"], r25, d["26H1_c"], r26, r26-r25))
rows_out.sort(key=lambda x: x[6])
print(f"{'律師':<10} {'25 group':<22} {'25諮詢':>7} {'25率':>6} {'26諮詢':>7} {'26率':>6} {'Δppt':>7}")
for name, g, c25, r25, c26, r26, dt in rows_out:
    print(f"{name:<10} {g:<22} {c25:>7} {r25:>5.1f}% {c26:>7} {r26:>5.1f}% {dt:>+6.1f}")
