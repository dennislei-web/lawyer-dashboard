"""從本地 xlsx 重新匯入所有 consultation_cases 到 Supabase
處理重複案件編號：同一案件編號保留已簽約 > 金額最高 > 最後一筆
"""
import pandas as pd
import httpx
import os
import sys
import io
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}"}

df = pd.read_excel(r"C:\Users\admin\Desktop\爬蟲\consultation_all_data.xlsx")
df.columns = df.columns.str.strip()

# 排除列入計算=否
calc_col = next((c for c in df.columns if "列入計算" in c), None)
if calc_col:
    df = df[~df[calc_col].astype(str).str.contains("否", na=False)]
    print(f"排除「列入計算=否」後: {len(df)} 筆")

# 律師對照
resp = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name"}, headers=headers)
lawyer_map = {l["name"]: l["id"] for l in resp.json()}
print(f"律師對照: {len(lawyer_map)} 位")

rev_col = next((c for c in df.columns if "應收" in c), None)
col_col = next((c for c in df.columns if "已收" in c), None)

if rev_col:
    df["revenue"] = pd.to_numeric(
        df[rev_col].astype(str).str.replace(",", "").str.strip(), errors="coerce"
    ).fillna(0)
if col_col:
    df["collected"] = pd.to_numeric(
        df[col_col].astype(str).str.replace(",", "").str.strip(), errors="coerce"
    ).fillna(0)

# 建立所有 case 資料
all_cases = {}  # case_number -> best row
skipped_lawyers = set()

for _, row in df.iterrows():
    lawyer_name = str(row.get("諮詢律師", "")).strip()
    lawyer_id = lawyer_map.get(lawyer_name)
    if not lawyer_id:
        skipped_lawyers.add(lawyer_name)
        continue
    cn = str(row.get("案件編號", "")).strip()
    if not cn or cn == "nan":
        continue
    sign_status = str(row.get("簽約狀態", "")).strip()
    is_signed = sign_status not in ("", "nan") and "未" not in sign_status

    case_type_col = next((c for c in df.columns if "服務項目" in c), None)
    case_type = str(row.get(case_type_col, "")).strip() if case_type_col else ""
    if case_type == "nan":
        case_type = ""

    client = str(row.get("當事人", "")).strip()
    if client == "nan":
        client = ""

    case_date = (
        row["諮詢日期"].strftime("%Y-%m-%d")
        if hasattr(row["諮詢日期"], "strftime")
        else str(row["諮詢日期"])[:10]
    )

    rev = int(float(row.get("revenue", 0) or 0))
    col = int(float(row.get("collected", 0) or 0))

    case_row = {
        "lawyer_id": lawyer_id,
        "case_date": case_date,
        "case_type": case_type,
        "case_number": cn,
        "client_name": client,
        "is_signed": is_signed,
        "revenue": rev,
        "collected": col,
    }

    # 重複案件編號處理：優先保留已簽約、金額最高的
    if cn in all_cases:
        existing = all_cases[cn]
        # 已簽約 > 未簽約
        if case_row["is_signed"] and not existing["is_signed"]:
            all_cases[cn] = case_row
        elif case_row["is_signed"] == existing["is_signed"]:
            # 同簽約狀態，取金額較高的
            if case_row["collected"] > existing["collected"]:
                all_cases[cn] = case_row
    else:
        all_cases[cn] = case_row

case_rows = list(all_cases.values())

if skipped_lawyers:
    # 只顯示單一律師名被跳過的（多律師名的是正常的聯合諮詢）
    single = [n for n in skipped_lawyers if "," not in n and n != "nan"]
    if single:
        print(f"跳過單一律師 (不在律師表): {single}")
    multi = len([n for n in skipped_lawyers if "," in n])
    if multi:
        print(f"跳過多律師聯合諮詢: {multi} 種組合")

print(f"去重後準備 upsert: {len(case_rows)} 筆")
high = [r for r in case_rows if r["collected"] >= 500000]
print(f"其中 >= 50萬: {len(high)} 筆")
for h in high:
    print(f"  {h['case_number']} | collected={h['collected']} | {h['case_date']} | signed={h['is_signed']}")

# Upsert
upsert_headers = {
    **headers,
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}
success = 0
failed = 0
for i in range(0, len(case_rows), 50):
    batch = case_rows[i : i + 50]
    resp = httpx.post(
        f"{url}/rest/v1/consultation_cases?on_conflict=case_number",
        json=batch,
        headers=upsert_headers,
        timeout=30,
    )
    if resp.status_code in (200, 201):
        success += len(batch)
    else:
        failed += len(batch)
        if failed <= 3:
            print(f"  batch {i} 失敗: {resp.status_code} {resp.text[:200]}")

print(f"\nupsert 完成: {success}/{len(case_rows)} 筆 (失敗: {failed})")
