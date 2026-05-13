"""
analyze_judicial_cross_referral.py — 找司法官承辦案中「非司法官自諮詢」的跨轉案

邏輯：
  1. 讀 cases.csv，篩 4 位司法官 + section='承辦' + 未作廢
  2. 拆 client 欄位（"A, B" → A, B）
  3. 對每位 client 查 consultation_cases，找出最接近案件日期的諮詢記錄
  4. 若諮詢律師 ∉ 4 位司法官，標為「跨轉」並輸出

輸出：
  - 終端：分類統計 + 律師-by-律師 摘要
  - judicial_cross_referral.csv：明細

使用：
  python scripts/partners/analyze_judicial_cross_referral.py
  python scripts/partners/analyze_judicial_cross_referral.py --verbose
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
H = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

JUDICIAL_LAWYERS = {"劉明潔", "方心瑜", "孫少輔", "許致維"}
# 合署內部諮詢人力（諮詢→司法官承辦不算跨轉）
COHORT_CONSULTANTS = {"曾秉浩", "劉誠夫"}
COHORT_FULL = JUDICIAL_LAWYERS | COHORT_CONSULTANTS

DEFAULT_CSV = Path(
    os.environ.get("PARTNERS_OUTPUT_DIR")
    or Path(os.environ.get("USERPROFILE") or os.path.expanduser("~")) / "Desktop" / "新增資料夾" / "合署律師分析_output"
) / "cases.csv"

OUTPUT_CSV = SCRIPT_DIR.parent.parent / "judicial_cross_referral.csv"


def split_clients(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in s.replace("、", ",").split(",")]
    return [p for p in parts if p]


def fetch_lawyers_id_to_name() -> dict[str, str]:
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        params={"select": "id,name"},
        headers=H, timeout=30, verify=_VERIFY,
    )
    resp.raise_for_status()
    return {r["id"]: r["name"] for r in resp.json()}


def fetch_consult_for_client(client: str) -> list[dict]:
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


def pick_nearest(cases: list[dict], target: date) -> dict | None:
    if not cases:
        return None
    signed = [c for c in cases if c.get("is_signed")]
    pool = signed if signed else cases
    before = [c for c in pool if c.get("case_date") and date.fromisoformat(c["case_date"]) <= target]
    if before:
        before.sort(key=lambda c: c["case_date"], reverse=True)
        return before[0]
    pool.sort(key=lambda c: abs((date.fromisoformat(c["case_date"]) - target).days) if c.get("case_date") else 99999)
    return pool[0]


def parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    print(f"CSV: {csv_path}")

    print("\n=== load lawyers ===")
    id_to_name = fetch_lawyers_id_to_name()
    print(f"  {len(id_to_name)} lawyers")

    print("\n=== load cases.csv ===")
    with open(csv_path, encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    print(f"  total rows: {len(rows)}")

    candidates = []
    for r in rows:
        if r.get("lawyer") not in JUDICIAL_LAWYERS:
            continue
        if r.get("section") != "承辦":
            continue
        if r.get("voided") == "是":
            continue
        d = parse_date(r.get("date", ""))
        if d is None:
            continue
        clients = split_clients(r.get("client", ""))
        for c in clients:
            candidates.append({
                "judicial": r["lawyer"],
                "year": r["year"], "month": r["month"], "date": d,
                "client": c, "amount": float(r.get("amount") or 0),
                "brand": r.get("brand"), "dept": r.get("dept"),
                "case_type": r.get("case_type"), "source": r.get("source"),
                "raw_client": r.get("client"), "handlers": r.get("handlers"),
            })
    print(f"  judicial 承辦 candidates (含拆 client): {len(candidates)}")

    # dedupe (judicial, client, date) to避免 amount 拆計重複
    seen = set()
    dedup = []
    for c in candidates:
        k = (c["judicial"], c["client"], c["date"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(c)
    print(f"  dedup (judicial × client × date): {len(dedup)}")

    print("\n=== fetch consultations ===")
    client_cache: dict[str, list[dict]] = {}
    unique_clients = sorted({c["client"] for c in dedup})
    for i, cl in enumerate(unique_clients, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(unique_clients)}")
        try:
            client_cache[cl] = fetch_consult_for_client(cl)
        except requests.HTTPError as e:
            print(f"  [WARN] {cl}: {e}")
            client_cache[cl] = []
    print(f"  fetched {len(unique_clients)} unique clients")

    # classify
    results = []
    for c in dedup:
        cases = client_cache.get(c["client"], [])
        picked = pick_nearest(cases, c["date"])
        if picked is None:
            cat = "no_consult"
            consult_lawyer = ""
        else:
            consult_lawyer = id_to_name.get(picked["lawyer_id"], "(unknown)")
            if consult_lawyer == c["judicial"]:
                cat = "self_consult"
            elif consult_lawyer in JUDICIAL_LAWYERS:
                cat = "cross_judicial"
            elif consult_lawyer in COHORT_CONSULTANTS:
                cat = "cohort_internal"
            else:
                cat = "cross_other"
        results.append({**c, "consult_lawyer": consult_lawyer, "category": cat,
                        "consult_date": picked["case_date"] if picked else "",
                        "consult_signed": picked.get("is_signed") if picked else None})

    # summary
    by_cat = defaultdict(int)
    by_cat_amt = defaultdict(float)
    by_judicial_cat = defaultdict(lambda: defaultdict(int))
    by_consult_lawyer = defaultdict(int)
    for r in results:
        by_cat[r["category"]] += 1
        by_cat_amt[r["category"]] += r["amount"]
        by_judicial_cat[r["judicial"]][r["category"]] += 1
        if r["category"] in ("cross_other", "cross_judicial"):
            by_consult_lawyer[r["consult_lawyer"]] += 1

    print("\n=== 總體分類（件數 / 金額）— 扣除曾秉浩/劉誠夫合署內部 ===")
    print(f"  self_consult   (司法官自諮詢自承辦): {by_cat['self_consult']:>4}  ${by_cat_amt['self_consult']:>12,.0f}")
    print(f"  cohort_internal(曾秉浩/劉誠夫諮詢): {by_cat['cohort_internal']:>4}  ${by_cat_amt['cohort_internal']:>12,.0f}")
    print(f"  cross_other    (真正外部跨轉):    {by_cat['cross_other']:>4}  ${by_cat_amt['cross_other']:>12,.0f}")
    print(f"  cross_judicial (司法官互轉):     {by_cat['cross_judicial']:>4}  ${by_cat_amt['cross_judicial']:>12,.0f}")
    print(f"  no_consult     (查無諮詢記錄):    {by_cat['no_consult']:>4}  ${by_cat_amt['no_consult']:>12,.0f}")

    print("\n=== by 司法官 ===")
    for j in sorted(JUDICIAL_LAWYERS):
        d = by_judicial_cat[j]
        print(f"  {j}: self={d['self_consult']:>3}  cohort_internal={d['cohort_internal']:>3}  "
              f"cross_other={d['cross_other']:>3}  cross_jud={d['cross_judicial']:>2}  no_consult={d['no_consult']:>3}")

    print("\n=== 跨轉來源律師 Top 15 ===")
    for name, cnt in sorted(by_consult_lawyer.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {name:8s} {cnt}")

    # write CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "category", "judicial", "client", "date", "amount",
            "consult_lawyer", "consult_date", "consult_signed",
            "year", "month", "brand", "dept", "case_type", "source",
            "raw_client", "handlers",
        ])
        w.writeheader()
        for r in results:
            row = {k: r.get(k) for k in w.fieldnames}
            if isinstance(row["date"], date):
                row["date"] = row["date"].isoformat()
            w.writerow(row)

    print(f"\n✓ wrote {OUTPUT_CSV}")

    if args.verbose:
        print("\n=== cross_other 明細（前 30 筆，依金額） ===")
        co = [r for r in results if r["category"] == "cross_other"]
        co.sort(key=lambda r: -r["amount"])
        for r in co[:30]:
            print(f"  {r['judicial']:6s} ← {r['consult_lawyer']:8s}  {r['date']}  "
                  f"{r['client']:8s}  ${r['amount']:>10,.0f}  ({r['dept']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
