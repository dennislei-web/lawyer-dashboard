"""
upload_cross_referral.py — 把 senior_profit_share.csv 的跨轉案 upsert 到 Supabase

第一版只做轉出方向（tier='喆律轉案'，200+ 件）：
  CSV 來源：senior_profit_share.csv（資深轉合署 cohort）
  目標表：partner_cross_referral

對每筆 tier='喆律轉案'：
  1. lookup partner_lawyer_id by name from public.lawyers
  2. 用 client_name + (year,month) 反推 referring_lawyer_id
     - GET consultation_cases?client_name=eq.{client}&order=case_date.desc
     - 多筆取 case_date 最接近 (year,month) 的那筆
  3. upsert 到 partner_cross_referral

使用方式：
  python scripts/partners/upload_cross_referral.py               # 預設讀 $PARTNERS_OUTPUT_DIR 或 Desktop 路徑
  python scripts/partners/upload_cross_referral.py --csv path    # 指定 CSV 檔
  python scripts/partners/upload_cross_referral.py --dry-run     # 只算不寫
  python scripts/partners/upload_cross_referral.py --verbose     # 印每筆細節

需要 scripts/.env 提供 SUPABASE_URL + SUPABASE_SERVICE_KEY。
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

# 某些 Python 環境（如新版 3.14 / 企業 proxy）沒設好 SSL CA bundle，導致
# Supabase 連線出 SSLCertVerificationError。優先用 certifi 的 cert path；
# 若仍失敗，可設 env INSECURE_SSL=1 暫時關閉 verify（僅本機 ETL 用）。
if os.environ.get("INSECURE_SSL", "").lower() in ("1", "true", "yes"):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _VERIFY = False
    print("⚠️  INSECURE_SSL=1: SSL verify is DISABLED", file=sys.stderr)
else:
    try:
        import certifi
        _VERIFY = certifi.where()
    except ImportError:
        _VERIFY = True

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
load_dotenv(REPO_ROOT / "scripts" / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

DEFAULT_CSV = Path(
    os.environ.get("PARTNERS_OUTPUT_DIR")
    or Path(os.environ.get("USERPROFILE") or os.path.expanduser("~")) / "Desktop" / "新增資料夾" / "合署律師分析_output"
) / "senior_profit_share.csv"


# 第一版只處理：senior cohort 的「喆律轉案」(轉出方向)
TARGET_TIERS_OUT = {"喆律轉案"}


def num(x):
    if x is None or x == "" or str(x).strip() == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def minguo_to_western(y: int) -> int:
    return int(y) + 1911


def fetch_lawyers_map() -> tuple[dict[str, str], set[str]]:
    """回傳 (name→uuid map, set of partner lawyer ids)。
    partner_terms IS NOT NULL 的視為合署律師（資深 + 司法官 cohort）。"""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        params={"select": "id,name,partner_terms"},
        headers=H,
        timeout=30,
        verify=_VERIFY,
    )
    resp.raise_for_status()
    name_map = {}
    partner_ids = set()
    for r in resp.json():
        name_map[r["name"]] = r["id"]
        if r.get("partner_terms") is not None:
            partner_ids.add(r["id"])
    return name_map, partner_ids


def fetch_consult_cases_by_client(client_name: str) -> list[dict]:
    """抓特定 client 的 consultation_cases（is_signed=true 優先）。"""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/consultation_cases",
        params={
            "select": "id,lawyer_id,case_date,is_signed,client_name",
            "client_name": f"eq.{client_name}",
            "order": "case_date.desc",
            "limit": "20",
        },
        headers=H,
        timeout=30,
        verify=_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def pick_referring_case(cases: list[dict], target_year: int, target_month: int, exclude_lawyer_ids: set[str] | None = None):
    """從 candidate cases 中挑最接近 (year, month) 的一筆。
    優先 is_signed=true，其次 case_date <= target 月底且最新。
    exclude_lawyer_ids：排除這些律師的 case（業務上：所有合署律師都不能當 referring，
    因為「跨轉」定義是諮詢律師→合署承辦，合署律師自己對到的諮詢記錄不算）"""
    if not cases:
        return None, "none"
    target = date(target_year, target_month, 1)

    if exclude_lawyer_ids:
        cases = [c for c in cases if c.get("lawyer_id") not in exclude_lawyer_ids]
        if not cases:
            return None, "none"

    # 偏好 is_signed=true 的
    signed = [c for c in cases if c.get("is_signed")]
    pool = signed if signed else cases

    # 對日期 <= target 的取最新；若無，取整體最近
    before = [c for c in pool if c.get("case_date") and date.fromisoformat(c["case_date"]) <= target]
    if before:
        before.sort(key=lambda c: c["case_date"], reverse=True)
        return before[0], ("exact" if len(before) == 1 and len(signed) == 1 else "nearest")
    pool.sort(key=lambda c: abs((date.fromisoformat(c["case_date"]) - target).days) if c.get("case_date") else 99999)
    return pool[0], "nearest"


def build_rows(csv_path: Path, lawyers_map: dict[str, str], partner_ids: set[str], verbose: bool = False) -> tuple[list[dict], dict]:
    """回傳 (rows_to_upsert, stats)。"""
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    with open(csv_path, encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))

    stats = defaultdict(int)
    out_rows = []

    # 先 group 同一 client 的查詢，避免重複打 API
    client_cache: dict[str, list[dict]] = {}

    for r in rows:
        tier = (r.get("tier") or "").strip()
        if tier not in TARGET_TIERS_OUT:
            continue
        stats["matched_tier"] += 1

        client = (r.get("client") or "").strip()
        if not client:
            stats["skipped_no_client"] += 1
            continue

        try:
            y_minguo = int(r["year"])
            m = int(r["month"])
        except (KeyError, TypeError, ValueError):
            stats["skipped_bad_date"] += 1
            continue
        y_western = minguo_to_western(y_minguo)

        partner_name = (r.get("lawyer") or "").strip()
        partner_id = lawyers_map.get(partner_name)
        if not partner_id:
            stats["skipped_unknown_partner"] += 1
            if verbose:
                print(f"  [WARN] 找不到合署律師 ID: {partner_name}")

        # client → consultation_cases lookup（快取）
        if client not in client_cache:
            try:
                client_cache[client] = fetch_consult_cases_by_client(client)
            except requests.HTTPError as e:
                if verbose:
                    print(f"  [WARN] 查 client={client} 失敗: {e}")
                client_cache[client] = []

        cases = client_cache[client]
        # 只排除「同一位 partner 本人」（避免自諮詢自承辦的記錄被選）；
        # 其他合署律師的諮詢記錄保留，由前端 LAWYER_DEPT_HISTORY 處理：
        # 例如李昭萱 114 年諮詢會被歸到中所（轉合署前），許煜婕會被歸到合署部門
        # （不在 OFFICE_TO_DEPT 範圍，自然不會算進任何分所 KPI）
        exclude_set = {partner_id} if partner_id else None
        picked, quality = pick_referring_case(cases, y_western, m, exclude_lawyer_ids=exclude_set)

        if picked:
            stats[f"join_{quality}"] += 1
        else:
            stats["join_none"] += 1

        row = {
            "year": y_minguo,
            "month": m,
            "direction": "out",
            "partner_lawyer_name": partner_name,
            "partner_lawyer_id": partner_id,
            "partner_cohort": "senior",
            "client_name": client,
            "case_amount": num(r.get("case_amount")),
            "firm_amount": num(r.get("zhelu_amt")),
            "lawyer_amount": num(r.get("lawyer_amt")),
            "raw_tier": tier,
            "referring_lawyer_id": picked["lawyer_id"] if picked else None,
            "consultation_case_id": picked["id"] if picked else None,
            "join_quality": quality,
        }
        out_rows.append(row)

        if verbose:
            tag = f"{quality:8s}" + (f" (signed={picked.get('is_signed')})" if picked else "")
            print(f"  {partner_name} {y_minguo}/{m:02d} {client:8s} ${row['case_amount']:>10.0f} → {tag}")

    # 聚合：同 (partner_name, year, month, client, raw_tier, case_amount) 的多筆合併
    # （CSV 可能同月分次收款出現多筆完全相同金額；upsert unique 衝突需先 dedupe）
    dedup_map: dict[tuple, dict] = {}
    for r in out_rows:
        key = (
            r["partner_lawyer_name"], r["year"], r["month"],
            r["client_name"], r["raw_tier"], r["case_amount"],
        )
        if key in dedup_map:
            cur = dedup_map[key]
            cur["firm_amount"] = (cur.get("firm_amount") or 0) + (r.get("firm_amount") or 0)
            cur["lawyer_amount"] = (cur.get("lawyer_amount") or 0) + (r.get("lawyer_amount") or 0)
            stats["deduped_merged"] += 1
        else:
            dedup_map[key] = r
    out_rows = list(dedup_map.values())

    return out_rows, dict(stats)


def upsert(rows: list[dict], batch_size: int = 200) -> None:
    if not rows:
        print("  no rows to upsert")
        return
    total = len(rows)
    print(f"  batch upsert {total} rows (batch_size={batch_size})")
    on_conflict = "partner_lawyer_name,year,month,client_name,raw_tier,case_amount"
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/partner_cross_referral?on_conflict={on_conflict}",
            headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=batch,
            timeout=60,
            verify=_VERIFY,
        )
        if not resp.ok:
            print(f"  [ERROR] batch {i}-{i+len(batch)}: {resp.status_code} {resp.text[:300]}")
            resp.raise_for_status()
        print(f"  ✓ batch {i+1}-{i+len(batch)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="senior_profit_share.csv 路徑")
    ap.add_argument("--dry-run", action="store_true", help="只算不寫")
    ap.add_argument("--verbose", action="store_true", help="印每筆細節")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    print(f"CSV: {csv_path}")
    print(f"Supabase: {SUPABASE_URL}")

    print("\n=== load lawyers map ===")
    lawyers_map, partner_ids = fetch_lawyers_map()
    print(f"  {len(lawyers_map)} lawyers  ({len(partner_ids)} partner)")

    print("\n=== build rows (tier=喆律轉案) ===")
    rows, stats = build_rows(csv_path, lawyers_map, partner_ids, verbose=args.verbose)
    print(f"\nStats:")
    for k, v in sorted(stats.items()):
        print(f"  {k:30s} {v}")

    if not rows:
        print("\n  no rows produced, exiting")
        return 0

    # 簡短按部門摘要（用 LAWYER_DEPARTMENTS map 的話需要在 Python 端 mirror）
    by_quality = defaultdict(int)
    for r in rows:
        by_quality[r["join_quality"]] += 1
    print(f"\nJoin quality breakdown:")
    for k, v in sorted(by_quality.items()):
        print(f"  {k:10s} {v}")

    if args.dry_run:
        print("\n--dry-run mode — not writing")
        # 印前 5 筆樣本
        print("\nSample rows:")
        for r in rows[:5]:
            print(f"  {r['partner_lawyer_name']} {r['year']}/{r['month']:02d} {r['client_name']} "
                  f"case={r['case_amount']} firm={r['firm_amount']} → referring={r['referring_lawyer_id']}")
        return 0

    print("\n=== upsert to Supabase ===")
    upsert(rows)
    print(f"\n✓ done. uploaded {len(rows)} cross-referral rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
