"""
scrape_case_lists.py
從 crm.lawyer 同步案件主檔到 Supabase.crm_cases。

兩階段：
  (1) 撈 /dashboard/case_lists 分頁，拿到 case_id + 基本欄位
  (2) 對每個 case_id 打 /api/cases/{id}，拿 aasm_state、時間軸、律師清單等

用法：
  python scripts/scrape_case_lists.py                 # 全量首爬
  python scripts/scrape_case_lists.py --recent N      # 只爬 list 前 N 頁（用於每日增量）
  python scripts/scrape_case_lists.py --refresh-open  # 只 refresh DB 中尚未終局的案件
  python scripts/scrape_case_lists.py --max N         # 只爬前 N 筆（測試用）
  python scripts/scrape_case_lists.py --start-page N  # 從第 N 頁開始（續爬用）

環境變數（scripts/.env）：
  SUPABASE_URL, SUPABASE_SERVICE_KEY, CRM_USERNAME, CRM_PASSWORD
"""

import argparse
import html as html_mod
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import functools
print = functools.partial(print, flush=True)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
REST_URL = f"{SUPABASE_URL}/rest/v1"
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal,resolution=merge-duplicates",
}

CRM_BASE_URL = "https://crm.lawyer"
CRM_LOGIN_URL = f"{CRM_BASE_URL}/users/sign_in"
CRM_USERNAME = os.environ["CRM_USERNAME"]
CRM_PASSWORD = os.environ["CRM_PASSWORD"]

# CRM API 之間的延遲（秒），避免打太快
API_DELAY = 0.15
# 批次大小（Supabase upsert）
BATCH_SIZE = 100
# 列表頁大小（CRM 固定 20）
LIST_PAGE_SIZE = 20


# ═══════════════════════════════════════════════════════════
#  CRM Login
# ═══════════════════════════════════════════════════════════
def crm_login():
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

    login_data = {
        "user[email]": CRM_USERNAME,
        "user[password]": CRM_PASSWORD,
        "user[remember_me]": "1",
        "commit": "登入",
        "authenticity_token": token or "",
    }
    resp = session.post(CRM_LOGIN_URL, data=login_data, allow_redirects=True)
    if "sign_in" in resp.url:
        raise Exception("CRM 登入失敗")
    print(f"✓ CRM 登入成功 ({CRM_USERNAME})")
    return session


# ═══════════════════════════════════════════════════════════
#  List page scrape
# ═══════════════════════════════════════════════════════════
def fetch_list_page(session, page=1, state="all", retries=5):
    """抓 case_lists 第 N 頁，回傳 (data_rows, total_count)。"""
    for attempt in range(retries + 1):
        try:
            resp = session.get(f"{CRM_BASE_URL}/dashboard/case_lists", params={
                "aasm_state": state,
                "case_label": "all",
                "department": "all",
                "group": "all",
                "office": "all",
                "related_person": "all",
                "role": "all",
                "page": page,
            }, timeout=60)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.find_all(attrs={"data-react-props": True}):
                if el.get("data-react-class") == "pages/CaseList/CaseListPage":
                    props = json.loads(html_mod.unescape(el.get("data-react-props", "{}")))
                    return props.get("data", []), props.get("total_count", 0)
            return [], 0
        except (requests.RequestException, requests.exceptions.ConnectionError) as e:
            wait = min(60, 5 * (attempt + 1))
            print(f"  ⚠ page {page} 抓取失敗 (嘗試 {attempt+1}/{retries+1}): {type(e).__name__}: {str(e)[:120]} → sleep {wait}s")
            time.sleep(wait)
    print(f"  ✗ page {page} 多次失敗，跳過")
    return [], 0


# ═══════════════════════════════════════════════════════════
#  Detail API
# ═══════════════════════════════════════════════════════════
def fetch_case_detail(session, case_id, retries=5):
    """打 /api/cases/{id}，回傳 JSON dict 或 None。"""
    url = f"{CRM_BASE_URL}/api/cases/{case_id}"
    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    for attempt in range(retries + 1):
        try:
            r = session.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (429, 502, 503):
                time.sleep(2 + attempt * 2)
                continue
        except (requests.RequestException, requests.exceptions.ConnectionError) as e:
            wait = min(30, 2 + attempt * 3)
            print(f"  ⚠ detail {case_id}: {type(e).__name__} → sleep {wait}s")
            time.sleep(wait)
    return None


# ═══════════════════════════════════════════════════════════
#  Transform
# ═══════════════════════════════════════════════════════════
def name_list(items, name_key="name"):
    """從 list of dict 抽 name；若 items 已是 string list 直接回。"""
    if not items:
        return []
    out = []
    for x in items:
        if isinstance(x, dict):
            v = x.get(name_key) or x.get("title") or ""
            if v:
                out.append(v)
        elif isinstance(x, str) and x:
            out.append(x)
    return out


def dict_name(d):
    if isinstance(d, dict):
        return d.get("name")
    return None


def transform(list_row, detail):
    """合併 list 欄位 + detail JSON → DB row dict。"""
    case_id = list_row["case_id"]

    # 當事人合併（個人 + 公司）
    clients_str = list_row.get("clients", "").strip()
    if detail:
        client_companies = detail.get("client_companies", []) or []
        if client_companies:
            companies = ", ".join(c.get("company_name", "") for c in client_companies if c.get("company_name"))
            if companies:
                clients_str = f"{clients_str}, {companies}".strip(", ").strip()

    row = {
        "case_id": case_id,
        "serial_number": list_row["serial_number"],
        # list 頁有的欄位
        "clients": clients_str or None,
        "adversaries": (list_row.get("adversaries") or "").strip() or None,
        "cause_of_action": (list_row.get("cause_of_action") or "").strip() or None,
        "case_type": list_row.get("type"),
        "case_labels": [l.get("name") for l in list_row.get("case_labels", []) if l.get("name")] or None,
        "last_of_record": list_row.get("last_of_record") or None,
        "last_of_court_record": list_row.get("last_of_court_record") or None,
        "next_of_court_record": list_row.get("next_of_court_record") or None,
        "synced_at": datetime.utcnow().isoformat() + "Z",
    }

    if detail:
        row.update({
            "aasm_state": detail.get("aasm_state"),
            "note": detail.get("note"),
            "internal_note": detail.get("internal_note"),
            "meeting_note": detail.get("meeting_note"),
            "unappointed_note": detail.get("unappointed_note"),
            "office_name": dict_name(detail.get("office")),
            "council_office_name": dict_name(detail.get("council_office")),
            "department_name": dict_name(detail.get("department")),
            "group_id": detail.get("group_id"),
            "council_lawyers":      name_list(detail.get("council_lawyer_list")),
            "assigned_members":     name_list(detail.get("assigned_member_list")),
            "litigation_lawyers":   name_list(detail.get("litigation_lawyer_list")),
            "pleading_lawyers":     name_list(detail.get("pleading_lawyer_list")),
            "complaint_lawyers":    name_list(detail.get("complaint_lawyer_list")),
            "in_court_lawyers":     name_list(detail.get("in_court_lawyer_list")),
            "managers":             name_list(detail.get("manager_list")),
            "clerks":                name_list(detail.get("clerk_list")),
            "client_sources":       name_list(detail.get("client_source_list")),
            "case_tags":            name_list(detail.get("case_tag_list")),
            "crm_created_at":    detail.get("created_at"),
            "crm_updated_at":    detail.get("updated_at"),
            "appointed_at":      detail.get("appointed_at"),
            "first_appointed_at": detail.get("first_appointed_at"),
            "pending_at":        detail.get("pending_at"),
            "closed_at":         detail.get("closed_at"),
            "canceled_at":       detail.get("canceled_at"),
            "unconcluded_at":    detail.get("unconcluded_at"),
            "unappointed_at":    detail.get("unappointed_at"),
            "price_target":      detail.get("price_target"),
            "detail_synced_at":  datetime.utcnow().isoformat() + "Z",
        })

    return row


# ═══════════════════════════════════════════════════════════
#  Upsert to Supabase
# ═══════════════════════════════════════════════════════════
def upsert_batch(rows):
    if not rows:
        return 0
    # 先在 client 端 dedupe（case_id 重複時取最後一筆）
    by_case = {}
    for r in rows:
        by_case[r["case_id"]] = r
    deduped = list(by_case.values())

    r = requests.post(
        f"{REST_URL}/crm_cases?on_conflict=case_id",
        headers=SB_HEADERS,
        json=deduped,
    )
    if r.status_code < 400:
        return len(deduped)

    # 整批失敗 → 拆單筆 upsert，跳過真的衝突的
    print(f"  ⚠ batch 失敗 {r.status_code}（{r.text[:150]}），切換到單筆 retry...")
    ok = 0
    for row in deduped:
        rr = requests.post(
            f"{REST_URL}/crm_cases?on_conflict=case_id",
            headers=SB_HEADERS,
            json=[row],
        )
        if rr.status_code < 400:
            ok += 1
        else:
            # 是 serial_number 衝突就試刪掉舊的 serial_number 共用列再 upsert
            if "serial_number" in rr.text:
                # 用 PATCH 強制更新該 case_id（serial_number 也會被覆寫）
                pr = requests.patch(
                    f"{REST_URL}/crm_cases?case_id=eq.{row['case_id']}",
                    headers=SB_HEADERS,
                    json=row,
                )
                if pr.status_code < 400:
                    ok += 1
                    continue
            print(f"    ✗ {row['serial_number']}: {rr.status_code} {rr.text[:120]}")
    return ok


def write_sync_status(status, message, **extra):
    payload = {
        "id": "crm_cases",
        "status": status,
        "message": message,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        **extra,
    }
    if status != "running":
        payload["finished_at"] = payload["updated_at"]
    try:
        requests.post(
            f"{REST_URL}/sync_status?on_conflict=id",
            headers=SB_HEADERS,
            json=payload,
        )
    except Exception as e:
        print(f"  ⚠ sync_status 寫入失敗: {e}")


# ═══════════════════════════════════════════════════════════
#  Strategies
# ═══════════════════════════════════════════════════════════
def crawl_all(session, start_page=1, max_records=None):
    """全量爬 list + detail。"""
    started_at = datetime.utcnow().isoformat() + "Z"
    write_sync_status("running", "全量首爬開始", started_at=started_at)

    # 先抓第一頁知道 total
    first_data, total = fetch_list_page(session, page=1, state="all")
    total_pages = (total + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE
    print(f"\n總案件數: {total}，總頁數: {total_pages}")
    if max_records:
        print(f"  (本次限制最多 {max_records} 筆)")

    state_counter = Counter()
    rows_buffer = []
    total_synced = 0
    total_detail_fetched = 0
    page_iter_start = start_page

    for page in range(page_iter_start, total_pages + 1):
        if page == 1 and start_page == 1:
            list_data = first_data
        else:
            list_data, _ = fetch_list_page(session, page=page, state="all")

        if not list_data:
            print(f"  page {page}: 空頁，跳過")
            continue

        for list_row in list_data:
            case_id = list_row["case_id"]
            detail = fetch_case_detail(session, case_id)
            total_detail_fetched += 1
            if detail:
                state_counter[detail.get("aasm_state") or "?"] += 1
            row = transform(list_row, detail)
            rows_buffer.append(row)

            if max_records and total_detail_fetched >= max_records:
                break

            time.sleep(API_DELAY)

            if len(rows_buffer) >= BATCH_SIZE:
                n = upsert_batch(rows_buffer)
                total_synced += n
                print(f"  page {page} | upsert {n} 筆 (累積 {total_synced}/{total_detail_fetched}) | state {dict(state_counter)}")
                rows_buffer = []

        if max_records and total_detail_fetched >= max_records:
            break

        # 每 5 頁更新一次 sync_status
        if page % 5 == 0:
            write_sync_status(
                "running",
                f"全量首爬中：page {page}/{total_pages}, 已處理 {total_detail_fetched} 筆",
                rows_scraped=total_detail_fetched, rows_updated=total_synced,
                started_at=started_at,
            )

    # 收尾
    if rows_buffer:
        n = upsert_batch(rows_buffer)
        total_synced += n
        print(f"  最終 upsert {n} 筆")

    print(f"\n{'='*60}")
    print(f"  完成：抓 {total_detail_fetched} 筆，同步 {total_synced} 筆")
    print(f"  aasm_state 分佈: {dict(state_counter)}")
    print(f"{'='*60}")

    write_sync_status(
        "success",
        f"全量首爬完成：{total_synced} 筆",
        rows_scraped=total_detail_fetched, rows_updated=total_synced,
        started_at=started_at,
    )


def crawl_recent(session, pages):
    """只爬最近 N 頁的 list + detail（每日增量用）。"""
    started_at = datetime.utcnow().isoformat() + "Z"
    rows_buffer = []
    total_synced = 0
    for page in range(1, pages + 1):
        list_data, _ = fetch_list_page(session, page=page, state="all")
        for list_row in list_data:
            detail = fetch_case_detail(session, list_row["case_id"])
            rows_buffer.append(transform(list_row, detail))
            time.sleep(API_DELAY)
        n = upsert_batch(rows_buffer)
        total_synced += n
        print(f"  page {page}: upsert {n} 筆")
        rows_buffer = []
    write_sync_status("success", f"增量 {pages} 頁完成：{total_synced} 筆",
                      rows_scraped=total_synced, rows_updated=total_synced,
                      started_at=started_at)


def refresh_open(session):
    """從 DB 撈 state_category != 'completed' 的案件，重打 detail 更新狀態。"""
    started_at = datetime.utcnow().isoformat() + "Z"
    print("從 DB 撈尚未終局的案件...")
    # state_category 不是 completed，或 aasm_state IS NULL
    r = requests.get(
        f"{REST_URL}/crm_cases",
        headers=SB_HEADERS,
        params={
            "select": "case_id,serial_number",
            "or": "(state_category.neq.completed,aasm_state.is.null)",
            "limit": "100000",
        },
    )
    cases = r.json()
    print(f"  找到 {len(cases)} 筆需要 refresh")

    # 為了 transform 我們也需要 list-page-only 欄位（last_of_record 等），但 refresh 主要關心狀態變動，所以只更新 detail 來的欄位
    rows_buffer = []
    total = 0
    for i, c in enumerate(cases, 1):
        detail = fetch_case_detail(session, c["case_id"])
        if not detail:
            continue
        row = {
            "case_id": c["case_id"],
            "serial_number": c["serial_number"],
            "aasm_state": detail.get("aasm_state"),
            "appointed_at": detail.get("appointed_at"),
            "first_appointed_at": detail.get("first_appointed_at"),
            "pending_at": detail.get("pending_at"),
            "closed_at": detail.get("closed_at"),
            "canceled_at": detail.get("canceled_at"),
            "unconcluded_at": detail.get("unconcluded_at"),
            "unappointed_at": detail.get("unappointed_at"),
            "crm_updated_at": detail.get("updated_at"),
            "detail_synced_at": datetime.utcnow().isoformat() + "Z",
            "synced_at": datetime.utcnow().isoformat() + "Z",
            "office_name": dict_name(detail.get("office")),
            "council_office_name": dict_name(detail.get("council_office")),
            "department_name": dict_name(detail.get("department")),
            "council_lawyers":   name_list(detail.get("council_lawyer_list")),
            "assigned_members":  name_list(detail.get("assigned_member_list")),
            "litigation_lawyers": name_list(detail.get("litigation_lawyer_list")),
            "managers":          name_list(detail.get("manager_list")),
            "client_sources":    name_list(detail.get("client_source_list")),
        }
        rows_buffer.append(row)
        time.sleep(API_DELAY)
        if len(rows_buffer) >= BATCH_SIZE:
            total += upsert_batch(rows_buffer)
            rows_buffer = []
            print(f"  refreshed {total}/{len(cases)}")
    if rows_buffer:
        total += upsert_batch(rows_buffer)
    write_sync_status("success", f"refresh-open 完成：{total} 筆", started_at=started_at)


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, help="只爬 list 前 N 頁")
    ap.add_argument("--refresh-open", action="store_true", help="只 refresh DB 中尚未終局的案件")
    ap.add_argument("--max", type=int, help="全量爬時最多處理 N 筆（測試用）")
    ap.add_argument("--start-page", type=int, default=1, help="全量爬從第 N 頁開始（續爬）")
    args = ap.parse_args()

    session = crm_login()

    if args.refresh_open:
        refresh_open(session)
    elif args.recent:
        crawl_recent(session, args.recent)
    else:
        crawl_all(session, start_page=args.start_page, max_records=args.max)


if __name__ == "__main__":
    main()
