"""2025-10/11 北一資料消失，去翻數據哪去了"""
import sys, io, urllib.request, urllib.parse, json
from collections import defaultdict
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

# 1. 整個集團 2025-10/11 各 group_name 收款
print("=== 2025-10 各 group_name 收款 ===")
rows = q_all("revenue_records", {
    "select": "record_date,office,group_name,amount,transaction_type",
    "record_date": "gte.2025-10-01",
    "transaction_type": "eq.PaymentTransaction",
})
oct_rows = [r for r in rows if (r.get("record_date") or "")[:7] == "2025-10"]
nov_rows = [r for r in rows if (r.get("record_date") or "")[:7] == "2025-11"]
print(f"\n2025-10 total rows: {len(oct_rows)}")
print(f"2025-11 total rows: {len(nov_rows)}")

def by_group(rs, label):
    agg = defaultdict(lambda: [0, 0])  # amt, count
    for r in rs:
        g = r.get("group_name") or "(NULL)"
        agg[g][0] += float(r.get("amount") or 0)
        agg[g][1] += 1
    print(f"\n--- {label} by group_name ---")
    for g, (a, n) in sorted(agg.items(), key=lambda x: -x[1][0]):
        if a < 10000: continue
        print(f"  {g:<35} {a/10000:>7.1f} 萬  ({n:>4} 筆)")
    print(f"  TOTAL: {sum(a for a,_ in agg.values())/10000:.1f} 萬")

by_group(oct_rows, "2025-10")
by_group(nov_rows, "2025-11")

# 2. office='台北所' 在 2025-10/11 的所有 group_name 分布（看是不是被 tag 到別處）
print("\n=== office='台北所' 在 2025-10/11 分布 ===")
tp = [r for r in oct_rows + nov_rows if r.get("office") == "台北所"]
agg = defaultdict(float)
for r in tp:
    g = r.get("group_name") or "(NULL)"
    agg[g] += float(r.get("amount") or 0)
print(f"  台北所 10+11 月 total: {sum(agg.values())/10000:.1f} 萬 ({len(tp)} 筆)")
for g, a in sorted(agg.items(), key=lambda x: -x[1]):
    if a < 10000: continue
    print(f"    {g:<35} {a/10000:>7.1f} 萬")

# 3. 比較 2025-09 vs 2025-10 vs 2025-11 vs 2025-12 各 office 的 trend
print("\n=== 各 office 月度 trend 2025-08 ~ 2026-01 ===")
all_rows = q_all("revenue_records", {
    "select": "record_date,office,amount,transaction_type",
    "record_date": "gte.2025-08-01",
})
mon = defaultdict(lambda: defaultdict(float))
for r in all_rows:
    if r.get("transaction_type") != "PaymentTransaction": continue
    m = (r.get("record_date") or "")[:7]
    o = r.get("office") or "(無)"
    mon[m][o] += float(r.get("amount") or 0)

offices = ["台北所","台中所","桃園所","新竹所","台南所","高雄所"]
print(f"\n{'月份':<10} " + "".join(f"{o:>10}" for o in offices))
for m in sorted(mon):
    if m > "2026-02": continue
    line = f"{m:<10} "
    for o in offices:
        v = mon[m][o]/10000
        line += f"{v:>10.0f}"
    print(line)

# 4. 看 department_revenue_summary 表 (per memory) 有沒有正確數字
print("\n=== department_revenue_summary 內容 ===")
try:
    drs = q_all("department_revenue_summary", {"select": "*"})
    print(f"  rows: {len(drs)}")
    if drs:
        print(f"  sample cols: {list(drs[0].keys())}")
        # filter 2025-10, 2025-11 if has month/period
        for r in drs[:5]:
            print(f"    {r}")
except Exception as e:
    print(f"  failed: {e}")
