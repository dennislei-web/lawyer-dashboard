"""
backfill_group_name.py
============================
回補 2025-06 以後 revenue_records.group_name = null 的記錄。

用法：
  python scripts/backfill_group_name.py                 # 乾跑（不寫 DB），印摘要 + 樣本
  python scripts/backfill_group_name.py --apply         # 實際 UPDATE
  python scripts/backfill_group_name.py --rollback FILE # 用 manifest 還原為 null

每次 --apply 會輸出 manifest JSON 檔到 scripts/_backfill_manifests/，
記錄每筆 transaction_id 的 (原 group_name=None, 新 group_name, 推算來源)。
"""
import argparse
import httpx
import json
import os
import sys
import io
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from group_inference import load_history

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import urllib3
urllib3.disable_warnings()
warnings.filterwarnings("ignore")

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": K, "Authorization": f"Bearer {K}"}
H_WRITE = {**H, "Content-Type": "application/json", "Prefer": "return=minimal"}

SINCE = "2025-06-01"  # 漏標問題起始日
MANIFEST_DIR = Path(__file__).parent / "_backfill_manifests"
MANIFEST_DIR.mkdir(exist_ok=True)


def fetch_null_group_records():
    """抓所有 group_name=null 且 record_date >= 2025-06-01 的 records"""
    rows, off, page = [], 0, 1000
    while True:
        r = httpx.get(
            f"{U}/rest/v1/revenue_records",
            params={
                "select": "id,transaction_id,record_date,office,assigned_lawyers,responsible_lawyer,amount,transaction_type,group_name,brand",
                "group_name": "is.null",
                "record_date": f"gte.{SINCE}",
                "is_void": "eq.false",
                "limit": str(page), "offset": str(off),
            },
            headers=H, timeout=120, verify=False,
        )
        r.raise_for_status()
        d = r.json()
        rows.extend(d)
        if len(d) < page: break
        off += page
    return rows


def run(apply_changes=False):
    print(f"[1/3] 載入 lawyer → group 歷史 (since 2024-01-01)...")
    history = load_history(U, K, verify=False, since_date="2024-01-01")
    print(f"      共 {len(history.all_lawyers)} 位律師有 group_name 歷史")

    print(f"\n[2/3] 抓漏標記錄 (group_name=null, record_date >= {SINCE})...")
    null_rows = fetch_null_group_records()
    print(f"      共 {len(null_rows)} 筆")

    # 推算
    inferences = []   # [(transaction_id, inferred_group, source)]
    no_match = []
    for r in null_rows:
        g, source = history.infer(r["record_date"], r.get("assigned_lawyers"), r.get("office"))
        if g:
            inferences.append({
                "transaction_id": r["transaction_id"],
                "record_date": r["record_date"],
                "office": r.get("office"),
                "assigned_lawyers": r.get("assigned_lawyers"),
                "amount": r.get("amount"),
                "old_group_name": None,
                "new_group_name": g,
                "source": source,
            })
        else:
            no_match.append(r)

    src_dist = Counter(i["source"] for i in inferences)
    grp_dist = Counter(i["new_group_name"] for i in inferences)

    print(f"\n[3/3] 推算結果")
    print(f"      可推: {len(inferences)} / {len(null_rows)} ({len(inferences)/max(len(null_rows),1)*100:.1f}%)")
    print(f"      無法推: {len(no_match)}")
    print(f"\n      推算來源分布:")
    for s, n in src_dist.most_common():
        print(f"        {s:<18} {n:>5}")
    print(f"\n      推回的 group_name 分布 (top 15):")
    for g, n in grp_dist.most_common(15):
        print(f"        {g:<28} {n:>5}")

    # 樣本
    print(f"\n      推算樣本 (前 10 筆):")
    for i in inferences[:10]:
        print(f"        {i['record_date']} | {i['office']:<6} | {(i['assigned_lawyers'] or '')[:25]:<25} | → {i['new_group_name']:<24} ({i['source']})")

    if no_match:
        print(f"\n      ⚠ 完全無法推的 {len(no_match)} 筆樣本:")
        for r in no_match[:5]:
            print(f"        {r['record_date']} | office={r.get('office')} | assigned={r.get('assigned_lawyers')}")

    if not apply_changes:
        print("\n[DRY RUN] 未寫入 DB。確認後再加 --apply 參數實際更新。")
        return

    # ─── 寫入 ───
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = MANIFEST_DIR / f"backfill_{ts}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "since": SINCE,
            "total_null": len(null_rows),
            "inferred": len(inferences),
            "no_match": len(no_match),
            "items": inferences,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[Manifest] 已儲存 → {manifest_path}")

    print(f"\n[寫入] 開始 UPDATE revenue_records ...")
    ok, fail = 0, 0
    for i, inf in enumerate(inferences):
        r = httpx.patch(
            f"{U}/rest/v1/revenue_records",
            params={"transaction_id": f"eq.{inf['transaction_id']}", "group_name": "is.null"},
            headers=H_WRITE,
            json={"group_name": inf["new_group_name"]},
            timeout=30, verify=False,
        )
        if 200 <= r.status_code < 300:
            ok += 1
        else:
            fail += 1
            if fail <= 5:
                print(f"   ⚠ 失敗 {inf['transaction_id']}: {r.status_code} {r.text[:120]}")
        if (i + 1) % 200 == 0:
            print(f"   ...已處理 {i+1}/{len(inferences)} (ok={ok}, fail={fail})")
    print(f"\n[完成] UPDATE 成功 {ok}, 失敗 {fail}")
    print(f"        Manifest: {manifest_path}")
    print(f"        若需還原: python scripts/backfill_group_name.py --rollback \"{manifest_path}\"")


def rollback(manifest_path):
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    print(f"[Rollback] 將還原 {len(items)} 筆為 group_name=null ...")
    ok, fail = 0, 0
    for i, inf in enumerate(items):
        # 只還原仍是我們寫的那個值的，避免覆蓋人工修正
        r = httpx.patch(
            f"{U}/rest/v1/revenue_records",
            params={
                "transaction_id": f"eq.{inf['transaction_id']}",
                "group_name": f"eq.{inf['new_group_name']}",
            },
            headers=H_WRITE,
            json={"group_name": None},
            timeout=30, verify=False,
        )
        if 200 <= r.status_code < 300: ok += 1
        else:
            fail += 1
            if fail <= 5: print(f"   ⚠ {inf['transaction_id']}: {r.status_code}")
        if (i+1) % 200 == 0: print(f"   ...{i+1}/{len(items)} (ok={ok})")
    print(f"[完成] 還原 {ok}, 失敗 {fail}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="實際寫入 DB（預設乾跑）")
    ap.add_argument("--rollback", help="manifest 路徑；還原該批次")
    args = ap.parse_args()
    if args.rollback:
        rollback(args.rollback)
    else:
        run(apply_changes=args.apply)
