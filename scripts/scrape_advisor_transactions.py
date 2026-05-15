"""
scrape_advisor_transactions.py
爬取 CRM 法顧對帳資訊頁面（/dashboard/advisor_transactions）→ 更新 Supabase advisor_transactions。

法顧客戶儲值帳本，現金流入口徑。跟 advisor_cases（Sheets 同步、成案口徑）是不同 SoT。

使用方式：
  python scripts/scrape_advisor_transactions.py                   # 更新本月
  python scripts/scrape_advisor_transactions.py --months 3        # 更新最近 3 個月
  python scripts/scrape_advisor_transactions.py --month 2026-03   # 更新指定月份

環境變數（或 .env）：
  SUPABASE_URL, SUPABASE_SERVICE_KEY, CRM_USERNAME, CRM_PASSWORD
"""

import argparse
import calendar
import functools
import html as html_mod
import json
import os
import sys
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from scrape_reconciliation import crm_login, CRM_BASE_URL

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
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

CRM_USERNAME = os.environ.get("CRM_USERNAME", "")
CRM_PASSWORD = os.environ.get("CRM_PASSWORD", "")


def scrape_advisor_transactions(session, start_date, end_date):
    """爬取法顧對帳資訊頁面，回傳交易記錄列表。"""
    url = f"{CRM_BASE_URL}/dashboard/advisor_transactions"
    params = {"start_date": start_date, "end_date": end_date}

    print(f"   爬取 {start_date} ~ {end_date} ...")
    resp = session.get(url, params=params)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    props_elements = soup.find_all(attrs={"data-react-props": True})

    data = []
    for el in props_elements:
        raw = el.get("data-react-props", "{}")
        try:
            props = json.loads(html_mod.unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(props, dict) and isinstance(props.get("data"), list) and props["data"]:
            data = props["data"]
            break

    print(f"   取得 {len(data)} 筆交易記錄")
    return data


def transform_record(item):
    """將 CRM 法顧交易記錄轉為 DB 格式。"""
    subj = item.get("subject") or {}
    payment_method = (item.get("payment_method") or {}).get("method")
    processed_at = item.get("processed_at", "") or ""
    record_date = processed_at[:10] if processed_at else None

    return {
        "transaction_id": item.get("id"),
        "record_date": record_date,
        "amount": item.get("amount") or 0,
        "point": item.get("point") or 0,
        "is_void": item.get("is_void", False),
        "notes": item.get("note"),
        "payment_method": payment_method,
        "client_name": subj.get("company_name"),
        "client_vat": subj.get("company_vat"),
        "subject_id": subj.get("id"),
        "organization_id": subj.get("organization_id"),
        "case_id": subj.get("case_id"),
        "contract_end_date": subj.get("contract_end_date"),
        "is_legal_advisor": subj.get("is_legal_advisor"),
        "total_point": subj.get("total_point"),
        "google_drive_link": subj.get("google_drive_link"),
        "raw_subject": subj,
    }


def upsert_records(records):
    batch_size = 50
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        resp = requests.post(
            f"{REST_URL}/advisor_transactions?on_conflict=transaction_id",
            headers=SB_HEADERS,
            json=batch,
        )
        if resp.status_code >= 400:
            print(f"   ⚠ Upsert 錯誤: {resp.status_code} {resp.text[:200]}")
        else:
            print(f"   已匯入 {min(i + batch_size, total)}/{total} 筆")


def get_month_range(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"


def iter_months(args):
    today = date.today()
    if args.month:
        y, m = map(int, args.month.split("-"))
        return [(y, m)]
    months = args.months or 1
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12; y -= 1
    return list(reversed(out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="指定月份 YYYY-MM")
    parser.add_argument("--months", type=int, help="抓最近 N 個月（含本月）")
    args = parser.parse_args()

    if not CRM_USERNAME or not CRM_PASSWORD:
        print("✗ 缺 CRM_USERNAME / CRM_PASSWORD")
        sys.exit(1)

    print("→ CRM 登入 ...")
    session = crm_login(CRM_USERNAME, CRM_PASSWORD)
    print("✓ 已登入\n")

    grand_total = 0
    for y, m in iter_months(args):
        start, end = get_month_range(y, m)
        items = scrape_advisor_transactions(session, start, end)
        if not items:
            print("   (該月無資料)\n")
            continue
        records = [transform_record(x) for x in items]
        deposit_amount = sum(r["amount"] for r in records if not r["is_void"])
        print(f"   {y}-{m:02d} 非作廢儲值合計：{deposit_amount:,.0f}")
        upsert_records(records)
        grand_total += deposit_amount
        print()

    print(f"✓ 完成。累計非作廢儲值：{grand_total:,.0f}")


if __name__ == "__main__":
    main()
