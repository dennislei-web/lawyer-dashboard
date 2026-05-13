"""
upload_judicial_cross_referral.py
---------------------------------
把司法官 cohort 的「外部跨轉案」灌進 partner_cross_referral 表
（partner_cohort='judicial'）。

來源：cases.csv（parse_judicial 輸出的 per-case 收入明細）
方法：對每筆司法官承辦案，用 client_name + date 反查 consultation_cases，
      找諮詢律師。若諮詢律師 ∉ {4 司法官 + 曾秉浩 + 劉誠夫} → 標為跨轉

跟 senior 版（upload_cross_referral.py）的差異：
  - source：cases.csv（per-case）vs senior_profit_share.csv（monthly aggregate）
  - tier：cases.csv 沒 tier 欄，全部標 raw_tier='喆律轉案'
  - cohort：寫死 'judicial'
  - firm_amount：暫不計算（司法官的 D 處理費是月度共擔，case-level 算不準），留 null

使用：
  INSECURE_SSL=1 python scripts/partners/upload_judicial_cross_referral.py --dry-run
  INSECURE_SSL=1 python scripts/partners/upload_judicial_cross_referral.py --verbose
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

if os.environ.get("INSECURE_SSL", "").lower() in ("1", "true", "yes"):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _VERIFY = False
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

JUDICIAL = {"劉明潔", "方心瑜", "孫少輔", "許致維"}
COHORT_CONSULTANTS = {"曾秉浩", "劉誠夫"}
COHORT_FULL = JUDICIAL | COHORT_CONSULTANTS
RAW_TIER = "喆律轉案"
MIN_AMOUNT = 2000  # 排除諮詢費收款 row（每場 $2,000），跟 senior 口徑一致

DEFAULT_CSV = Path(
    os.environ.get("PARTNERS_OUTPUT_DIR")
    or Path(os.environ.get("USERPROFILE") or os.path.expanduser("~")) / "Desktop" / "新增資料夾" / "合署律師分析_output"
) / "cases.csv"


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def fetch_lawyers():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        params={"select": "id,name"},
        headers=H, timeout=30, verify=_VERIFY,
    )
    resp.raise_for_status()
    name_to_id, id_to_name = {}, {}
    for r in resp.json():
        name_to_id[r["name"]] = r["id"]
        id_to_name[r["id"]] = r["name"]
    return name_to_id, id_to_name


def fetch_consult(client: str):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/consultation_cases",
        params={
            "select": "id,lawyer_id,case_date,is_signed,client_name",
            "client_name": f"eq.{client}",
            "order": "case_date.desc",
            "limit": "20",
        },
        headers=H, timeout=30, verify=_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def pick_nearest(cases, target: date, exclude_ids: set | None = None):
    if not cases:
        return None, "none"
    if exclude_ids:
        cases = [c for c in cases if c.get("lawyer_id") not in exclude_ids]
        if not cases:
            return None, "none"
    signed = [c for c in cases if c.get("is_signed")]
    pool = signed if signed else cases
    before = [c for c in pool if c.get("case_date") and date.fromisoformat(c["case_date"]) <= target]
    if before:
        before.sort(key=lambda c: c["case_date"], reverse=True)
        return before[0], "nearest" if len(before) > 1 else "exact"
    pool.sort(key=lambda c: abs((date.fromisoformat(c["case_date"]) - target).days) if c.get("case_date") else 99999)
    return pool[0], "nearest"


def split_clients(s):
    if not s:
        return []
    parts = [p.strip() for p in str(s).replace("、", ",").split(",")]
    return [p for p in parts if p]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print(f"CSV: {args.csv}")

    name_to_id, id_to_name = fetch_lawyers()
    print(f"loaded {len(name_to_id)} lawyers")

    cohort_ids = {name_to_id[n] for n in COHORT_FULL if n in name_to_id}

    # 讀 cases.csv，篩 4 司法官 + 承辦 + 未作廢
    with open(args.csv, encoding="utf-8-sig") as fp:
        all_rows = list(csv.DictReader(fp))

    candidates = []
    for r in all_rows:
        if r.get("lawyer") not in JUDICIAL:
            continue
        if r.get("section") != "承辦":
            continue
        if r.get("voided") == "是":
            continue
        d = parse_date(r.get("date", ""))
        if d is None:
            continue
        amt = float(r.get("amount") or 0)
        if amt <= MIN_AMOUNT:
            continue  # 諮詢費收款 row（$2,000/場），不算委任案
        for client in split_clients(r.get("client", "")):
            candidates.append({
                "judicial": r["lawyer"], "year": int(r["year"]), "month": int(r["month"]),
                "client": client, "amount": amt, "date": d,
                "raw_client": r.get("client"),
            })

    # dedup
    seen = set()
    dedup = []
    for c in candidates:
        k = (c["judicial"], c["client"], c["date"], c["amount"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(c)
    print(f"司法官承辦 dedup: {len(dedup)} (from {len(candidates)} raw)")

    # fetch consultations
    client_cache = {}
    unique_clients = sorted({c["client"] for c in dedup})
    print(f"fetching consultations for {len(unique_clients)} unique clients...")
    for i, cl in enumerate(unique_clients, 1):
        if i % 100 == 0:
            print(f"  {i}/{len(unique_clients)}")
        try:
            client_cache[cl] = fetch_consult(cl)
        except requests.HTTPError as e:
            print(f"  [WARN] {cl}: {e}")
            client_cache[cl] = []

    # classify
    cross_rows = []
    stats = defaultdict(int)
    for c in dedup:
        partner_id = name_to_id.get(c["judicial"])
        if not partner_id:
            stats["no_partner_id"] += 1
            continue
        cases = client_cache.get(c["client"], [])
        # 排除司法官本人的諮詢記錄
        picked, quality = pick_nearest(cases, c["date"], exclude_ids={partner_id})
        if picked is None:
            stats["no_consult"] += 1
            continue
        consult_lawyer_id = picked["lawyer_id"]
        consult_lawyer_name = id_to_name.get(consult_lawyer_id, "(unknown)")

        # 分類
        if consult_lawyer_name in COHORT_FULL:
            # 含 4 司法官（互轉）跟曾秉浩/劉誠夫（內部）— 都不算外部跨轉
            stats["cohort_internal_or_judicial"] += 1
            continue

        stats["cross_other"] += 1
        cross_rows.append({
            "year": c["year"], "month": c["month"], "direction": "out",
            "partner_lawyer_name": c["judicial"], "partner_lawyer_id": partner_id,
            "partner_cohort": "judicial",
            "client_name": c["client"],
            "case_amount": c["amount"],
            "firm_amount": None,  # 司法官 D 月度共擔，case-level 算不準，留 null
            "lawyer_amount": None,
            "raw_tier": RAW_TIER,
            "referring_lawyer_id": consult_lawyer_id,
            "consultation_case_id": picked["id"],
            "join_quality": quality,
        })

    print("\n=== Stats ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:30s} {v}")
    print(f"  → cross_rows to upload: {len(cross_rows)}")

    # 同 key dedup before upsert（unique index = partner_lawyer_name,year,month,client_name,raw_tier,case_amount）
    by_key = {}
    for r in cross_rows:
        k = (r["partner_lawyer_name"], r["year"], r["month"], r["client_name"], r["raw_tier"], r["case_amount"])
        # 同 key 取 join_quality 較好的
        if k in by_key:
            stats["dedup_merged"] += 1
            continue
        by_key[k] = r
    cross_rows = list(by_key.values())
    print(f"  after dedup: {len(cross_rows)}")

    if args.verbose:
        print("\n=== sample rows ===")
        for r in cross_rows[:10]:
            print(f"  {r['partner_lawyer_name']} {r['year']}/{r['month']:02d} {r['client_name']:12s} "
                  f"${r['case_amount']:>10,.0f}  ← {id_to_name.get(r['referring_lawyer_id'], '?')} [{r['join_quality']}]")

    if args.dry_run:
        print("\n--dry-run, not uploading")
        return 0

    if not cross_rows:
        print("\nno rows to upload")
        return 0

    print("\n=== upsert to Supabase ===")
    on_conflict = "partner_lawyer_name,year,month,client_name,raw_tier,case_amount"
    batch_size = 200
    for i in range(0, len(cross_rows), batch_size):
        batch = cross_rows[i:i + batch_size]
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/partner_cross_referral?on_conflict={on_conflict}",
            headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=batch, timeout=60, verify=_VERIFY,
        )
        if not resp.ok:
            print(f"  [ERROR] batch {i}-{i+len(batch)}: {resp.status_code} {resp.text[:400]}")
            resp.raise_for_status()
        print(f"  ✓ batch {i+1}-{i+len(batch)}")

    print(f"\n✓ uploaded {len(cross_rows)} judicial cross-referral rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
