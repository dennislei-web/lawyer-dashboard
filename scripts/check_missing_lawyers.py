"""檢查 CRM 中找不到的律師 vs Supabase lawyers 表"""
import os, io, sys
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

# CRM 中找不到的律師
missing = ["林昀", "吳柏慶", "林桑羽", "李家泓", "許致維", "劉誠夫"]

# 取得所有 Supabase 律師
resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name,email,is_active,office", "order": "name"}, headers=headers)
lawyers = resp.json()
lawyer_names = {l["name"]: l for l in lawyers}

print("=== CRM 找不到的律師 ===")
for name in missing:
    if name in lawyer_names:
        l = lawyer_names[name]
        print(f"  ✓ {name} 已在 Supabase (active={l['is_active']}, email={l.get('email','')})")
    else:
        # 嘗試模糊比對
        similar = [n for n in lawyer_names if any(c in n for c in name)]
        print(f"  ✗ {name} 不在 Supabase")
        if similar:
            print(f"    相似名稱: {', '.join(similar)}")

# 也反向檢查：CRM xlsx 中有哪些律師名字
print("\n=== 從 xlsx 讀取 CRM 律師名單 ===")
try:
    import pandas as pd
    xlsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "consultation_all_data.xlsx")
    df = pd.read_excel(xlsx_path)
    crm_lawyers = df["諮詢律師"].dropna().unique()
    print(f"  CRM 中共有 {len(crm_lawyers)} 位律師")

    # 找出不在 Supabase 的
    not_in_sb = [n for n in crm_lawyers if n not in lawyer_names]
    if not_in_sb:
        print(f"\n  CRM 有但 Supabase 沒有 ({len(not_in_sb)} 位):")
        for n in sorted(not_in_sb):
            print(f"    - {n}")

    # 找出名字可能是組合的（CRM 可能把多位律師合在一起）
    combo = [n for n in crm_lawyers if ", " in str(n) or "," in str(n) or "、" in str(n)]
    if combo:
        print(f"\n  可能是組合名稱:")
        for n in combo:
            print(f"    - {n}")
except Exception as e:
    print(f"  Error: {e}")
