import sys, io, urllib.request, urllib.parse, json
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "https://zpbkeyhxyykbvownrngf.supabase.co"
import os; KEY = os.environ["SUPABASE_SERVICE_KEY"]

def q(path, params=None):
    url = f"{URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
    })
    return json.loads(urllib.request.urlopen(req).read())

def q_all(path, params=None, page=1000):
    out = []
    offset = 0
    while True:
        p = dict(params or {})
        p["limit"] = str(page)
        p["offset"] = str(offset)
        chunk = q(path, p)
        out.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return out

# 1. all offices
print("=== distinct office values ===")
r = q_all("revenue_records", {"select": "office"})
c = Counter(x["office"] for x in r if x.get("office"))
for k, v in c.most_common():
    print(f"  {k!r}: {v}")

print("\n=== distinct transaction_type ===")
r = q_all("revenue_records", {"select": "transaction_type"})
c = Counter(x["transaction_type"] for x in r if x.get("transaction_type"))
for k, v in c.most_common():
    print(f"  {k!r}: {v}")

print("\n=== distinct group_name (top 40) ===")
r = q_all("revenue_records", {"select": "group_name"})
c = Counter(x["group_name"] for x in r if x.get("group_name"))
for k, v in c.most_common(40):
    print(f"  {k!r}: {v}")

print(f"\ntotal rows scanned: {len(r)}")
