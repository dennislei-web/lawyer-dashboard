"""
backfill_partner_attribution.py

對 revenue_records 套 lawyers.partner_terms 計算 firm_amount + attribution_basis。

使用方式：
  python scripts/backfill_partner_attribution.py                # 預設 2025-10 ~ 今日
  python scripts/backfill_partner_attribution.py --start 2026-01-01 --end 2026-01-31
  python scripts/backfill_partner_attribution.py --dry-run      # 只算不寫
  python scripts/backfill_partner_attribution.py --verify-only  # 只跑 11501 雪莉驗證
"""

import argparse
import os
import sys
from datetime import date

import requests
import warnings
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv("scripts/.env")

# 公司 proxy MITM TLS：requests 用全域 Session + verify=False 統一處理
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore")
_session = requests.Session()
_session.verify = False
requests.get = _session.get
requests.post = _session.post

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


# 合署生效日：在某律師正式加入合署之前，其收款一律視為所內（firm_default，不套拆帳）。
# 與 public/revenue/index.html 的 PARTNER_SINCE 對齊；此處只需含有 partner_terms 的律師。
# 沒列在這裡的 partner 預設視為「一直都是合署」（不 gating），以保留舊行為。
PARTNER_SINCE = {
    "許煜婕": "2024-11-01",
    "李昭萱": "2025-06-01",
    "柯雪莉": "2025-09-01",
    "黃顯皓": "2025-10-01",
}


def split_lawyers(s):
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def first_partner_in_list(lawyers, terms_map):
    """從 assigned_lawyers 列表中（依順序）找出第一個有 partner_terms 的律師。"""
    for name in lawyers:
        if name in terms_map:
            return name
    return None


def attribute(rec, terms_map):
    """回傳 (firm_amount, basis, partner_name)。amount 在 CRM 退款也是正數，這裡用 transaction_type 判斷正負。"""
    amt = float(rec.get("amount") or 0)
    g = rec.get("group_name") or ""
    ttype = rec.get("transaction_type") or ""
    lawyers = split_lawyers(rec.get("assigned_lawyers"))

    sign = -1 if ttype == "RefundTransaction" else 1
    base_amt = abs(amt) * sign

    partner_name = first_partner_in_list(lawyers, terms_map)
    if not partner_name:
        return base_amt, "firm_default", None

    # 合署生效日 gating：紀錄日早於該 partner 轉合署日 → 當時是受雇/所內，整筆算所內
    since = PARTNER_SINCE.get(partner_name)
    rec_date = (rec.get("record_date") or "")[:10]
    if since and rec_date and rec_date < since:
        return base_amt, "firm_default", None

    terms = terms_map[partner_name]

    consult_fee_amount = float(terms.get("consult_fee_amount") or 0)
    self_take_firm_pct = float(terms.get("self_take_firm_pct") or 0)
    consult_fee_firm_pct = float(terms.get("consult_fee_firm_pct") or 0)
    case_close_firm_pct = float(terms.get("case_close_firm_pct") or 0)
    self_take_inc_consult = bool(terms.get("self_take_includes_consult_fee", True))

    # 自合署組判定：group_name 含「合署」+「partner 律師名字」
    is_self_partner_group = ("合署" in g) and (partner_name in g)
    is_consult_fee_amount = abs(amt) == consult_fee_amount

    if is_self_partner_group:
        if is_consult_fee_amount and not self_take_inc_consult:
            return base_amt * consult_fee_firm_pct, "consult_fee", partner_name
        return base_amt * self_take_firm_pct, "self_take", partner_name
    if is_consult_fee_amount:
        return base_amt * consult_fee_firm_pct, "consult_fee", partner_name
    return base_amt * case_close_firm_pct, "case_close", partner_name


def fetch_partner_lawyers():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        headers=H,
        params={"select": "name,partner_terms", "partner_terms": "not.is.null"},
    )
    r.raise_for_status()
    return {row["name"]: row["partner_terms"] for row in r.json()}


def fetch_records(start_date, end_date):
    """抓全欄位 — upsert 用得上 NOT NULL 欄位（amount、transaction_type 等）。"""
    all_rows = []
    page = 0
    page_size = 1000
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/revenue_records",
            headers=H,
            params=[
                ("select", "*"),
                ("is_void", "eq.false"),
                ("record_date", "gte." + start_date),
                ("record_date", "lte." + end_date),
                ("order", "record_date.asc"),
                ("limit", str(page_size)),
                ("offset", str(page * page_size)),
            ],
        )
        r.raise_for_status()
        rows = r.json()
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return all_rows


def upsert_attributions(rows_to_update, batch_size=200):
    """批次 upsert（merge-duplicates）。rows_to_update 是含完整欄位 + 已套 firm_amount 的 dicts。"""
    total = len(rows_to_update)
    print(f"  批次 upsert {total} 筆，每批 {batch_size}")
    for i in range(0, total, batch_size):
        batch = rows_to_update[i:i + batch_size]
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/revenue_records?on_conflict=transaction_id",
            headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=batch,
            timeout=60,
        )
        if resp.status_code >= 400:
            print(f"  ⚠ Upsert 錯誤 ({i}~{i+len(batch)}): {resp.status_code} {resp.text[:200]}")
        else:
            print(f"  已寫入 {min(i + batch_size, total)}/{total}")


def verify_xueli_11501(rows, terms_map):
    """跟雪莉 Excel 11501 結算對驗"""
    print("\n=== 11501 雪莉驗證 ===")
    if "柯雪莉" not in terms_map:
        print("  雪莉沒有 partner_terms，跳過")
        return

    self_take_total = 0.0
    consult_fee_total = 0.0
    case_close_total = 0.0
    firm_self = 0.0
    firm_consult = 0.0
    firm_case = 0.0

    for rec in rows:
        if rec["record_date"][:7] != "2026-01":
            continue
        firm_amt, basis, partner = attribute(rec, terms_map)
        if partner != "柯雪莉":
            continue
        amt = float(rec.get("amount") or 0)
        if rec.get("transaction_type") == "RefundTransaction":
            amt = -amt
        if basis == "self_take":
            self_take_total += amt
            firm_self += firm_amt
        elif basis == "consult_fee":
            consult_fee_total += amt
            firm_consult += firm_amt
        elif basis == "case_close":
            case_close_total += amt
            firm_case += firm_amt

    print(f"  自帶承辦: {self_take_total:>10,.0f} → 喆律拿 {firm_self:>9,.0f}（雪莉拿 {self_take_total - firm_self:,.0f}）")
    print(f"  諮詢費(2k): {consult_fee_total:>9,.0f} → 喆律拿 {firm_consult:>9,.0f}")
    print(f"  案件成案:  {case_close_total:>10,.0f} → 喆律拿 {firm_case:>9,.0f}")
    print(f"  Excel 11501 結算（雪莉應付）：")
    print(f"    自帶承辦 187,000 × 70% = 130,900（律師）+ 56,100（喆律）")
    print(f"    諮詢費 13 場 × 2,000 = 26,000（律師）")
    print(f"    成案獎金 60,000 × 5% = 3,000（律師）")
    print(f"    Total 雪莉應付 = 159,900；喆律利潤 = 56,100 - 29,000 = 27,100")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-10-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true", help="只算不寫")
    parser.add_argument("--verify-only", action="store_true", help="只跑驗證不寫")
    args = parser.parse_args()

    print(f"範圍: {args.start} ~ {args.end}")
    print("Loading partner_terms...")
    terms_map = fetch_partner_lawyers()
    print(f"  Partners with terms: {list(terms_map.keys())}")

    print("Loading records...")
    rows = fetch_records(args.start, args.end)
    print(f"  Total records: {len(rows)}")

    # 驗證
    verify_xueli_11501(rows, terms_map)

    if args.verify_only:
        return

    # 計算 + 套上 firm_amount / attribution_basis
    basis_counts = {}
    rows_to_update = []
    for rec in rows:
        firm_amt, basis, _partner = attribute(rec, terms_map)
        existing_amt = rec.get("firm_amount")
        existing_basis = rec.get("attribution_basis")
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        if (existing_amt is None or float(existing_amt) != firm_amt
                or existing_basis != basis):
            rec["firm_amount"] = firm_amt
            rec["attribution_basis"] = basis
            rows_to_update.append(rec)

    print(f"\n計算結果（含未變化）:")
    for k, v in sorted(basis_counts.items()):
        print(f"  {k}: {v}")
    print(f"  待寫入: {len(rows_to_update)}")

    if args.dry_run:
        print("(dry-run，跳過寫入)")
        return

    if rows_to_update:
        print(f"\n寫入 Supabase...")
        upsert_attributions(rows_to_update)
        print(f"完成。")


if __name__ == "__main__":
    main()
