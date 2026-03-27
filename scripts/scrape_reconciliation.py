"""
scrape_reconciliation.py
爬取 CRM 對帳資訊頁面 → 更新 Supabase revenue_records。

使用方式：
  python scripts/scrape_reconciliation.py                     # 更新本月
  python scripts/scrape_reconciliation.py --months 3          # 更新最近 3 個月
  python scripts/scrape_reconciliation.py --month 2026-03     # 更新指定月份

環境變數（或 .env）：
  SUPABASE_URL, SUPABASE_SERVICE_KEY, CRM_USERNAME, CRM_PASSWORD
"""

import argparse
import html as html_mod
import json
import os
import re
import sys
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
REST_URL = f"{SUPABASE_URL}/rest/v1"
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation,resolution=merge-duplicates",
}

CRM_BASE_URL = "https://crm.lawyer"
CRM_LOGIN_URL = f"{CRM_BASE_URL}/users/sign_in"
CRM_USERNAME = os.environ.get("CRM_USERNAME", "")
CRM_PASSWORD = os.environ.get("CRM_PASSWORD", "")

# 所有部門 group IDs（從 CRM URL 取得）
ALL_GROUPS = (
    "c18b5155-310f-42e9-aa19-106db89f2a60,"
    "b22f2cb8-9b55-46f3-84a5-2adf7053c52e,"
    "9faee83e-e9ca-429b-88f9-bd2d13fc14e0,"
    "4dcfa60a-ac67-442c-ab44-9f0aded75499,"
    "19d4dc43-dcb1-4234-9a5e-c0ea8a72d9aa,"
    "7f459997-0d2b-4c64-86be-b543d584ef85,"
    "ccc4bc42-0328-4b51-8a8c-cce2082f5079,"
    "c498a0c0-37a2-4201-b4de-5af339381a1e,"
    "22e9be67-1cc5-42d8-b8f4-4decbbf4c0ee,"
    "e24da6f6-920a-4e2a-ac02-bde282986ad8,"
    "8aa327ba-2abc-4700-9fce-47bb13208ec4,"
    "3f83d3f6-7610-49b5-a060-62adeaa1898b,"
    "b24a4b91-c058-469a-9233-f2589c5910ab,"
    "31df98a0-5032-4072-9ff7-1c47a3dd8126,"
    "5ae8cf10-5596-4bd0-9e24-9e69af595d76,"
    "4abe1b81-2bcb-47c1-befe-93dc7d18ba63,"
    "2ca446d6-ca35-490b-8cb3-9b414c419652,"
    "87cb66bf-a2eb-446a-8dc3-8a0b29d044b6,"
    "9a08e3f7-6b4e-475c-9bbd-aaafb8456109,"
    "a219eac6-f564-4e92-8ebb-00d850aae218,"
    "7d471d9b-6eef-4f9c-8dd0-afbe5152ed46,"
    "4a4b7b07-bb4b-404c-9f26-f57096a03733,"
    "57c50abc-58dd-452b-9910-1f8378070548,"
    "bd4f2954-2b9b-4e2c-be70-25cac26e2731,"
    "99452c6f-f5ed-439c-b0c4-dbb0545a6644,"
    "nil"
)


# ═══════════════════════════════════════════════════════════
#  CRM Login
# ═══════════════════════════════════════════════════════════
def crm_login(email, password):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    })

    resp = session.get(CRM_LOGIN_URL)
    soup = BeautifulSoup(resp.text, "html.parser")

    token = None
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta:
        token = meta.get("content")
    if not token:
        hidden = soup.find("input", {"name": "authenticity_token"})
        if hidden:
            token = hidden.get("value")

    login_data = {
        "user[email]": email,
        "user[password]": password,
        "user[remember_me]": "1",
        "commit": "登入",
    }
    if token:
        login_data["authenticity_token"] = token

    resp = session.post(CRM_LOGIN_URL, data=login_data, allow_redirects=True)
    if "sign_in" not in resp.url and "login" not in resp.url:
        return session

    raise Exception("CRM 登入失敗")


# ═══════════════════════════════════════════════════════════
#  Scrape Reconciliation Page
# ═══════════════════════════════════════════════════════════
def scrape_reconciliation(session, start_date, end_date):
    """爬取對帳頁面，回傳交易記錄列表。"""
    url = f"{CRM_BASE_URL}/dashboard/finance/reconciliation"
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "groups": ALL_GROUPS,
    }

    print(f"   爬取 {start_date} ~ {end_date} ...")
    resp = session.get(url, params=params)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # 找到包含資料的 React props 元素
    props_elements = soup.find_all(attrs={"data-react-props": True})

    data = []
    for el in props_elements:
        raw = el.get("data-react-props", "{}")
        try:
            props = json.loads(html_mod.unescape(raw))
        except json.JSONDecodeError:
            continue
        if "data" in props and isinstance(props["data"], list) and len(props["data"]) > 0:
            data = props["data"]
            break

    print(f"   取得 {len(data)} 筆交易記錄")
    return data


# ═══════════════════════════════════════════════════════════
#  Transform CRM Data → DB Records
# ═══════════════════════════════════════════════════════════
def transform_record(item):
    """將 CRM 交易記錄轉為 DB 格式。"""
    case = item.get("case_service_item", {}).get("case", {}) or {}

    # 客戶來源（可能有多個）
    client_sources = case.get("client_sources", [])
    source_channel = ", ".join(s.get("name", "") for s in client_sources) if client_sources else None

    # 當事人
    clients = case.get("clients", [])
    client_name = ", ".join(c.get("name", "") for c in clients) if clients else None

    # 負責人員 (assigned_members)
    assigned = case.get("assigned_members", [])
    responsible = ", ".join(a.get("name", "") for a in assigned) if assigned else None

    # 接案律師 (council_lawyers)
    council = case.get("council_lawyers", [])
    assigned_lawyers = ", ".join(a.get("name", "") for a in council) if council else None

    # 服務項目
    items = item.get("case_service_item", {}).get("items", [])
    service_items = ", ".join(i.get("name", "") for i in items) if items else None

    # 日期
    processed_at = item.get("processed_at", "")
    record_date = processed_at[:10] if processed_at else None

    return {
        "transaction_id": item.get("id"),
        "record_date": record_date,
        "amount": item.get("amount", 0),
        "transaction_type": item.get("type"),  # PaymentTransaction / RefundTransaction
        "is_void": item.get("is_void", False),
        "payment_method": item.get("payment_method", {}).get("method"),
        "client_name": client_name,
        "responsible_lawyer": responsible,
        "assigned_lawyers": assigned_lawyers,
        "brand": case.get("department", {}).get("name") if case.get("department") else None,
        "office": case.get("council_office", {}).get("name") if case.get("council_office") else None,
        "group_name": case.get("group", {}).get("name") if case.get("group") else None,
        "source_channel": source_channel,
        "service_items": service_items,
        "accrued_expense": item.get("case_service_item", {}).get("accrued_expense", 0),
        "notes": item.get("note"),
    }


# ═══════════════════════════════════════════════════════════
#  Upsert to Supabase
# ═══════════════════════════════════════════════════════════
def upsert_records(records):
    """批次 upsert 到 Supabase。"""
    batch_size = 50
    total = len(records)

    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        resp = requests.post(
            f"{REST_URL}/revenue_records?on_conflict=transaction_id",
            headers=SB_HEADERS,
            json=batch,
        )
        if resp.status_code >= 400:
            print(f"   ⚠ Upsert 錯誤: {resp.status_code} {resp.text[:200]}")
        else:
            print(f"   已匯入 {min(i + batch_size, total)}/{total} 筆")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
def get_month_range(year, month):
    """回傳 (start_date, end_date) 字串。"""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"


def main():
    parser = argparse.ArgumentParser(description="爬取 CRM 對帳資訊")
    parser.add_argument("--month", help="指定月份 (例: 2026-03)")
    parser.add_argument("--months", type=int, help="最近 N 個月")
    args = parser.parse_args()

    print("═══ CRM 對帳資訊爬蟲 ═══\n")

    # 計算要爬的月份
    today = date.today()
    months_to_scrape = []

    if args.month:
        y, m = map(int, args.month.split("-"))
        months_to_scrape.append((y, m))
    elif args.months:
        for i in range(args.months):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            months_to_scrape.append((y, m))
    else:
        months_to_scrape.append((today.year, today.month))

    # 登入 CRM
    print("1. 登入 CRM...")
    session = crm_login(CRM_USERNAME, CRM_PASSWORD)
    print("   ✓ 登入成功\n")

    # 爬取每個月份
    all_records = []
    print("2. 爬取對帳資料...")
    for year, month in months_to_scrape:
        start_date, end_date = get_month_range(year, month)
        raw_data = scrape_reconciliation(session, start_date, end_date)
        records = [transform_record(item) for item in raw_data]
        all_records.extend(records)

    print(f"\n   共取得 {len(all_records)} 筆記錄\n")

    # 匯入 Supabase
    print("3. 匯入 Supabase...")
    if all_records:
        upsert_records(all_records)
    else:
        print("   沒有資料需要匯入")

    print(f"\n═══ 完成！共處理 {len(all_records)} 筆 ═══")


if __name__ == "__main__":
    main()
