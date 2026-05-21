"""探查 monthly_stats + lawyers 表結構"""
import sys, io, urllib.request, urllib.parse, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "https://zpbkeyhxyykbvownrngf.supabase.co"
import os; KEY = os.environ["SUPABASE_SERVICE_KEY"]

def q(path, params, page=1000):
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

# monthly_stats sample
print("=== monthly_stats 5 samples ===")
rows = q("monthly_stats", {"select": "*", "limit": "5", "order": "month.desc"})
for r in rows[:5]:
    print(f"  {r}")

# lawyers sample
print("\n=== lawyers 5 samples ===")
rows = q("lawyers", {"select": "*", "limit": "5"})
for r in rows[:5]:
    print(f"  {r}")

# 看 lawyers 表欄位
print("\n=== lawyers columns ===")
if rows:
    print(f"  {list(rows[0].keys())}")
