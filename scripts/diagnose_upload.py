"""
診斷：為什麼蘇思蓓上傳的琬琪/又仁/奕靖 115/01-03 諮詢資料看不到
"""
import httpx, os, io, sys
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

TARGETS = ["蘇思蓓", "琬琪", "又仁", "奕靖"]

# 1) 找律師（模糊比對，因為檔名可能只寫 '琬琪' 或 '琬琪律師'）
print("=" * 70)
print("[1] 律師檔案（lawyers 表）")
print("=" * 70)
r = httpx.get(f"{url}/rest/v1/lawyers",
              params={"select": "id,name,email,role,is_active,auth_user_id"},
              headers=headers)
all_lawyers = r.json()
matched = {}
for name_frag in TARGETS:
    hits = [l for l in all_lawyers if name_frag in l["name"]]
    print(f"\n  「{name_frag}」匹配 {len(hits)} 位：")
    for l in hits:
        auth = "Y" if l.get("auth_user_id") else "N"
        print(f"    - name={l['name']:<6} id={l['id']} role={l['role']} active={l['is_active']} auth={auth}")
        matched[l["name"]] = l["id"]

# 2) 撈 consultation_cases 115/01-03（2026-01-01 ~ 2026-03-31）
print("\n" + "=" * 70)
print("[2] consultation_cases 中 2026-01-01 ~ 2026-03-31 的資料")
print("=" * 70)
r = httpx.get(f"{url}/rest/v1/consultation_cases",
              params={
                  "select": "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,meeting_record,transcript,created_at",
                  "case_date": "gte.2026-01-01",
                  "and": "(case_date.lte.2026-03-31)",
                  "order": "created_at.desc",
                  "limit": "500",
              },
              headers=headers)
cases = r.json() if r.status_code == 200 else []
print(f"\n  總筆數：{len(cases)}")

# 按律師歸類
by_lawyer = {}
for c in cases:
    by_lawyer.setdefault(c["lawyer_id"], []).append(c)

# name lookup
id_to_name = {l["id"]: l["name"] for l in all_lawyers}

print("\n  各律師筆數（115/01-03）：")
for lid, rows in sorted(by_lawyer.items(), key=lambda x: -len(x[1])):
    nm = id_to_name.get(lid, "<unknown>")
    has_mr = sum(1 for x in rows if x.get("meeting_record"))
    has_ts = sum(1 for x in rows if x.get("transcript"))
    print(f"    {nm:<6} | 筆數={len(rows):>3} | 有會議記錄={has_mr:>3} | 有逐字稿={has_ts:>3}")

# 3) 重點：目標三位律師有沒有資料
print("\n  目標律師（琬琪/又仁/奕靖）明細：")
for name_frag in ["琬琪", "又仁", "奕靖"]:
    hits_in_lawyers = [l for l in all_lawyers if name_frag in l["name"]]
    for l in hits_in_lawyers:
        lid = l["id"]
        rows = by_lawyer.get(lid, [])
        print(f"\n    【{l['name']}】({lid[:8]}...) 115/01-03 共 {len(rows)} 筆")
        for c in rows[:10]:
            mr = "有" if c.get("meeting_record") else "無"
            ts = "有" if c.get("transcript") else "無"
            sign = "成案" if c.get("is_signed") else "未成案"
            print(f"       {c['case_date']} | {sign} | {c['case_type'][:20]:<20} | MR={mr} TS={ts} | created={c['created_at'][:10]}")

# 4) sync_status — 最近的同步紀錄
print("\n" + "=" * 70)
print("[3] sync_status — 最近 15 筆同步紀錄")
print("=" * 70)
try:
    r = httpx.get(f"{url}/rest/v1/sync_status",
                  params={"select": "*", "order": "created_at.desc", "limit": "15"},
                  headers=headers)
    for s in r.json():
        print(f"  {s.get('created_at','')[:19]} | {s}")
except Exception as e:
    print(f"  Error: {e}")

# 5) 蘇思蓓最近建立了哪些 cases（用 created_at 看）
print("\n" + "=" * 70)
print("[4] consultation_cases 最近 created 的 30 筆（看上傳行為）")
print("=" * 70)
r = httpx.get(f"{url}/rest/v1/consultation_cases",
              params={
                  "select": "case_date,case_type,lawyer_id,created_at,is_signed,meeting_record,transcript,case_number",
                  "order": "created_at.desc",
                  "limit": "30",
              },
              headers=headers)
for c in r.json():
    nm = id_to_name.get(c["lawyer_id"], "?")
    mr = "MR" if c.get("meeting_record") else "  "
    ts = "TS" if c.get("transcript") else "  "
    print(f"  created={c['created_at'][:19]} | case_date={c['case_date']} | {nm:<6} | {mr} {ts} | {c['case_number'][:30]}")
