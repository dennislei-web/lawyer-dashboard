"""找 2025 北所一部單筆大額 + 黃顯皓案件流向校驗"""
import sys, io, urllib.request, urllib.parse, json
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

# 1. 2025 北所一部 top 20 單筆 PaymentTransaction
print("=== 2025 北所一部 top 20 單筆收款 ===")
rows = q_all("revenue_records", {
    "select": "record_date,group_name,service_items,amount,responsible_lawyer,source_channel,assigned_lawyers",
    "group_name": "eq.北所一部",
    "record_date": "gte.2025-01-01",
    "transaction_type": "eq.PaymentTransaction",
    "order": "amount.desc",
})
# filter 2025 only client-side
rows25 = [r for r in rows if r.get("record_date","").startswith("2025")]
rows25.sort(key=lambda r: -float(r.get("amount") or 0))
for r in rows25[:20]:
    amt = float(r.get("amount") or 0)
    lw = r.get("responsible_lawyer") or "?"
    si = (r.get("service_items") or "")[:30]
    print(f"  {r['record_date']}  {amt/10000:>7.1f}萬  律師:{lw:<8} 案型:{si}")

print(f"\n2025 北一最大 5 筆合計: {sum(float(r['amount']) for r in rows25[:5])/10000:.1f} 萬")
print(f"2025 北一全部:        {sum(float(r['amount']) for r in rows25)/10000:.1f} 萬")

# 2. 北一 2025 vs 2026 月度 trend，看 700 萬出現在哪個月
print("\n=== 2025-2026 北所一部 月度趨勢 ===")
all_rows = q_all("revenue_records", {
    "select": "record_date,amount,transaction_type",
    "group_name": "eq.北所一部",
    "record_date": "gte.2025-01-01",
})
from collections import defaultdict
mon = defaultdict(lambda: {"pay":0,"ref":0})
for r in all_rows:
    m = (r.get("record_date") or "")[:7]
    if not m: continue
    amt = float(r.get("amount") or 0)
    if r.get("transaction_type") == "PaymentTransaction":
        mon[m]["pay"] += amt
    else:
        mon[m]["ref"] += abs(amt)
for m in sorted(mon):
    d = mon[m]
    print(f"  {m}: 收 {d['pay']/10000:>7.1f}萬  退 {d['ref']/10000:>5.1f}萬")

# 3. 黃顯皓 案件流向：他是 responsible_lawyer / assigned 但 group_name 不是合署黃顯皓的單
print("\n=== 黃顯皓 in responsible_lawyer / assigned_lawyers 但記入非合署 group ===")
# 先 fetch 全部跟黃顯皓有關的
rows_h = q_all("revenue_records", {
    "select": "record_date,group_name,responsible_lawyer,assigned_lawyers,amount,transaction_type,service_items",
    "or": "(responsible_lawyer.eq.黃顯皓,assigned_lawyers.cs.{黃顯皓})",
    "record_date": "gte.2025-01-01",
})
from collections import Counter
g_count = Counter()
g_amt = defaultdict(float)
for r in rows_h:
    if r.get("transaction_type") != "PaymentTransaction": continue
    g = r.get("group_name") or "(無)"
    amt = float(r.get("amount") or 0)
    g_count[g] += 1
    g_amt[g] += amt
print(f"  黃顯皓涉案總筆數: {sum(g_count.values())}")
for g, n in g_count.most_common():
    print(f"    {g:<32} {n:>4} 筆  {g_amt[g]/10000:>7.1f} 萬")
