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
from collections import Counter

from group_inference import load_history

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

load_dotenv()

# group_name 推算：在 main() 進來時 lazy load 一次
_GROUP_HISTORY = None
_INFER_STATS = Counter()

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

# 部門 group：不再 hardcode group IDs。
# 原本寫死一份 group 清單，每當 CRM 新增部門（如律師轉合署 → 新 group），
# 清單就漏掉，該部門案件整批抓不到（曾漏 北所合署蘇萱/李家泓 = 數十萬）。
# 對帳 endpoint 省略 groups 參數時會回傳「所有部門」，與 CRM 對帳頁總額口徑一致，
# 且未來新部門自動納入，免維護。


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
    # 不帶 groups 參數 = 抓所有部門（含未來新增的合署 group），與 CRM 對帳頁總額一致
    params = {
        "start_date": start_date,
        "end_date": end_date,
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

    # 當事人 — 個人戶在 case.clients[].name，公司戶在 case.client_companies[].company_name
    clients = case.get("clients", []) or []
    client_companies = case.get("client_companies", []) or []
    parts = [c.get("name", "") for c in clients] + [cc.get("company_name", "") for cc in client_companies]
    parts = [p for p in parts if p]
    client_name = ", ".join(parts) if parts else None

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

    office = case.get("council_office", {}).get("name") if case.get("council_office") else None
    group_name = case.get("group", {}).get("name") if case.get("group") else None

    # CRM 端 group 為空時，從歷史律師→group 對應推算（避免部門儀表板失真）
    if not group_name and _GROUP_HISTORY is not None:
        inferred, source = _GROUP_HISTORY.infer(record_date, assigned_lawyers, office)
        if inferred:
            group_name = inferred
            _INFER_STATS[source] += 1
        else:
            _INFER_STATS["no_match"] += 1

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
        "office": office,
        "group_name": group_name,
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


SYNC_STATUS_ID = "daily_revenue"


def write_sync_status(status, message, scraped_months="", rows_scraped=0, rows_updated=0, started_at=None):
    """將同步結果寫入 sync_status 表（id='daily_revenue'）；失敗不影響主流程。"""
    now_iso = datetime.utcnow().isoformat() + "Z"
    payload = {
        "id": SYNC_STATUS_ID,
        "status": status,
        "message": message,
        "scraped_months": scraped_months,
        "rows_scraped": rows_scraped,
        "rows_updated": rows_updated,
        "started_at": started_at,
        "finished_at": None if status == "running" else now_iso,
        "updated_at": now_iso,
    }
    try:
        resp = requests.post(
            f"{REST_URL}/sync_status",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 400:
            print(f"   (sync_status 寫入失敗 {resp.status_code}: {resp.text[:120]})")
    except Exception as e:
        print(f"   (sync_status 寫入失敗: {e})")


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

    sorted_months = sorted(months_to_scrape)
    month_label = (
        f"{sorted_months[0][0]}-{sorted_months[0][1]:02d}"
        if len(sorted_months) == 1
        else f"{sorted_months[0][0]}-{sorted_months[0][1]:02d}~{sorted_months[-1][0]}-{sorted_months[-1][1]:02d}"
    )
    started_at = datetime.utcnow().isoformat() + "Z"
    write_sync_status("running", f"正在更新 {month_label}...", month_label, started_at=started_at)

    try:
        # 登入 CRM
        print("1. 登入 CRM...")
        session = crm_login(CRM_USERNAME, CRM_PASSWORD)
        print("   ✓ 登入成功\n")

        # 載入 group_name 歷史（用於 ingest 時自動補 null group_name）
        global _GROUP_HISTORY
        print("2. 載入律師 → group 對應表（推算 fallback 用）...")
        try:
            _GROUP_HISTORY = load_history(SUPABASE_URL, SUPABASE_KEY, verify=False)
            print(f"   ✓ 已載入 {len(_GROUP_HISTORY.all_lawyers)} 位律師歷史\n")
        except Exception as e:
            print(f"   ⚠ 載入失敗，將略過自動推算: {e}\n")
            _GROUP_HISTORY = None

        # 爬取每個月份
        all_records = []
        print("3. 爬取對帳資料...")
        for year, month in months_to_scrape:
            start_date, end_date = get_month_range(year, month)
            raw_data = scrape_reconciliation(session, start_date, end_date)
            records = [transform_record(item) for item in raw_data]
            all_records.extend(records)

        print(f"\n   共取得 {len(all_records)} 筆記錄")
        if _INFER_STATS:
            total_inferred = sum(n for k, n in _INFER_STATS.items() if k != "no_match")
            print(f"   📌 group_name 推算: {total_inferred} 筆（CRM 空值已自動補），無法推: {_INFER_STATS.get('no_match', 0)}")
            for src, n in _INFER_STATS.most_common():
                print(f"      {src}: {n}")
        print()

        # 匯入 Supabase
        print("4. 匯入 Supabase...")
        rows_updated = 0
        if all_records:
            upsert_records(all_records)
            rows_updated = len(all_records)
        else:
            print("   沒有資料需要匯入")

        print(f"\n═══ 完成！共處理 {len(all_records)} 筆 ═══")
        write_sync_status(
            "success",
            f"更新完成 {month_label}",
            month_label,
            rows_scraped=len(all_records),
            rows_updated=rows_updated,
            started_at=started_at,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        write_sync_status(
            "error",
            f"更新失敗：{str(e)[:200]}",
            month_label,
            started_at=started_at,
        )
        raise


if __name__ == "__main__":
    main()
