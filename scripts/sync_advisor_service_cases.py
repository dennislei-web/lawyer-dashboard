"""
sync_advisor_service_cases.py
法顧委後案件保險網同步：advisor_transactions（CRM 儲值）→ advisor_service_cases

每日跑（掛在 update-revenue.yml 的 advisor_transactions 爬蟲之後）：
1. CRM 出現新的法顧儲值客戶、但委後案件表沒有 → 自動建案
   - 合約效期內或點數有餘額 → 服務中
   - 合約過期但點數有剩      → 續約評估
2. 既有案件「空欄位」回填（只填 NULL/空值，絕不覆蓋使用者編輯）：
   - 統編、合約迄日、已購時數、電話、雲端資料夾(handover._cloud)
   - 承辦律師 / 業務 / 所別（從 advisor_cases 成案清單比對）

環境變數（或 scripts/.env）：
  SUPABASE_URL=https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
"""

import os
import re
import sys
from datetime import date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

IMPORT_NOTE = "由 CRM 儲值紀錄自動同步建案"


def normalize_name(name: str) -> str:
    """對齊前端 normalizeClientName：去掉「（前名稱：…）」alias"""
    if not name:
        return ""
    return re.sub(r"[（(]前名稱[：:][^）)]*[）)]", "", str(name)).strip()


def fetch_all(table: str, select: str, extra: str = "") -> list:
    """PostgREST 分頁抓全量"""
    rows, offset, page = [], 0, 1000
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}{extra}&offset={offset}&limit={page}"
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def main():
    today = date.today().isoformat()

    # ── 1. 聚合 CRM 儲值 per client ─────────────────────────
    txs = fetch_all(
        "advisor_transactions",
        "client_name,client_vat,record_date,point,total_point,contract_end_date,is_void,is_legal_advisor,raw_subject",
    )
    crm = {}
    for t in txs:
        if t.get("is_void") or t.get("is_legal_advisor") is False:
            continue
        name = (t.get("client_name") or "").strip()
        if not name:
            continue
        rec = crm.setdefault(name, {
            "vat": None, "purchased_min": 0.0, "balance_min": None, "balance_date": "",
            "contract_end": None, "phone": None, "drive": None, "last_date": "",
        })
        rec["purchased_min"] += float(t.get("point") or 0)
        rd = t.get("record_date") or ""
        if t.get("total_point") is not None and rd >= rec["balance_date"]:
            rec["balance_min"] = float(t["total_point"])
            rec["balance_date"] = rd
        ce = t.get("contract_end_date")
        if ce and (rec["contract_end"] is None or ce > rec["contract_end"]):
            rec["contract_end"] = ce
        if t.get("client_vat") and not rec["vat"]:
            rec["vat"] = t["client_vat"]
        raw = t.get("raw_subject") or {}
        if rd >= rec["last_date"]:
            rec["last_date"] = rd
            phone = (raw.get("mobile_number") or raw.get("company_phone_number")
                     or raw.get("phone_number") or "").strip()
            if phone:
                rec["phone"] = phone
            drive = (raw.get("google_drive_link") or "").strip()
            if drive:
                rec["drive"] = drive

    # ── 2. 成案清單 → 承辦律師 / 業務 / 所別 對照 ───────────
    cases = fetch_all("advisor_cases", "client_name,handling_lawyers,salesperson,office,paid_at")
    cases.sort(key=lambda c: c.get("paid_at") or "")  # 後蓋前 = 取最新
    people = {}
    for c in cases:
        key = normalize_name(c.get("client_name"))
        if not key:
            continue
        cur = people.setdefault(key, {})
        if c.get("handling_lawyers"):
            cur["handling_lawyer"] = "、".join(c["handling_lawyers"])
        if c.get("salesperson"):
            cur["salesperson"] = c["salesperson"]
        if c.get("office"):
            cur["office"] = c["office"]

    # ── 3. 既有委後案件 ─────────────────────────────────────
    existing = fetch_all(
        "advisor_service_cases",
        "id,client_name,client_vat,client_phone,contract_end,purchased_hours,"
        "handling_lawyer,salesperson,office,handover,stage",
    )
    existing_names = {e["client_name"] for e in existing}

    # ── 4. 新客戶建案 ───────────────────────────────────────
    inserts = []
    for name, rec in crm.items():
        if name in existing_names:
            continue
        bal = rec["balance_min"] or 0
        ce = rec["contract_end"]
        active = (ce and ce >= today) or bal > 0
        if not active:
            continue
        stage = "續約評估" if (ce and ce < today) else "服務中"
        p = people.get(normalize_name(name), {})
        handover = {"_cloud": rec["drive"]} if rec["drive"] else {}
        inserts.append({
            "client_name": name,
            "client_vat": rec["vat"],
            "client_phone": rec["phone"],
            "case_type": "法律顧問",
            "stage": stage,
            "salesperson": p.get("salesperson"),
            "office": p.get("office"),
            "handling_lawyer": p.get("handling_lawyer"),
            "contract_end": ce,
            "purchased_hours": round(rec["purchased_min"] / 60.0, 1) if rec["purchased_min"] else None,
            "handover": handover,
            "note": f"{today} {IMPORT_NOTE}",
        })
    if inserts:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/advisor_service_cases",
                          headers={**HEADERS, "Prefer": "return=minimal"}, json=inserts, timeout=60)
        r.raise_for_status()
    print(f"新建案件：{len(inserts)} 筆" + (f"（{'、'.join(i['client_name'] for i in inserts[:5])}…）" if inserts else ""))

    # ── 5. 既有案件空欄位回填 ───────────────────────────────
    patched = 0
    for e in existing:
        rec = crm.get(e["client_name"])
        p = people.get(normalize_name(e["client_name"]), {})
        patch = {}
        if not e.get("client_vat") and rec and rec["vat"]:
            patch["client_vat"] = rec["vat"]
        if not e.get("client_phone") and rec and rec["phone"]:
            patch["client_phone"] = rec["phone"]
        if not e.get("contract_end") and rec and rec["contract_end"]:
            patch["contract_end"] = rec["contract_end"]
        if e.get("purchased_hours") is None and rec and rec["purchased_min"]:
            patch["purchased_hours"] = round(rec["purchased_min"] / 60.0, 1)
        if not e.get("handling_lawyer") and p.get("handling_lawyer"):
            patch["handling_lawyer"] = p["handling_lawyer"]
        if not e.get("salesperson") and p.get("salesperson"):
            patch["salesperson"] = p["salesperson"]
        if not e.get("office") and p.get("office"):
            patch["office"] = p["office"]
        handover = e.get("handover") or {}
        if not (handover.get("_cloud") or "").strip() and rec and rec["drive"]:
            handover["_cloud"] = rec["drive"]
            patch["handover"] = handover
        if patch:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/advisor_service_cases?id=eq.{e['id']}",
                headers={**HEADERS, "Prefer": "return=minimal"}, json=patch, timeout=60)
            r.raise_for_status()
            patched += 1
    print(f"空欄位回填：{patched} 筆")


if __name__ == "__main__":
    main()
