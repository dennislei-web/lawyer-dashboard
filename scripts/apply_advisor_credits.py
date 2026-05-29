"""一次性把法顧初次諮詢進案 credit（表一）materialize 到線上 DB。

兩階段：
  (A) consultation_cases：每筆 credit 的 collected/revenue PATCH 成「絕對值 base+add」
      → idempotent，重跑回到同一值。
  (B) monthly_stats：對受影響的 (律師, 月) 桶，把 credit「加上去」現有值。
      不用 rebuild_monthly_stats 全量重建，因為那會連帶還原 daily_update 的
      利衝排除等調整（blast radius 太大）。此階段為加性，故用 marker 檔擋重跑，
      避免重複加倍；要強制重套用加 --force-monthly。

平時 daily_update.py 已 wire advisor_credits，每次 CRM 同步後會自動以
「base+credit 絕對覆寫」重套用，此腳本只用於現在立刻讓線上儀表板反映。

預設 dry-run，加 --apply 才實際寫。
"""
import os
import io
import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import httpx
from dotenv import load_dotenv

from advisor_credits import load_credits

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env")
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
MARKER = SCRIPT_DIR / "briefs" / "raw_data" / ".advisor_credits_monthly_applied.json"


def apply_consultation_cases(credits, do_write):
    print("[A] consultation_cases（絕對 base+add，idempotent）")
    ok = miss = 0
    for c in credits:
        cn = c["case_number"]
        add = int(round(c["add_amount"]))
        target_col = int(round(c["base_collected"])) + add
        target_rev = int(round(c["base_revenue"])) + add
        r = httpx.get(f"{URL}/rest/v1/consultation_cases",
                      params={"case_number": f"eq.{cn}", "select": "case_number,collected,revenue"},
                      headers=HDR, timeout=30)
        r.raise_for_status()
        found = r.json()
        if not found:
            print(f"  ✗ 找不到 case_number={cn}（{c['lawyer']} {c['client'][:12]}）")
            miss += 1
            continue
        cur = found[0]
        print(f"  {c['lawyer']:<4}{c['client'][:14]:<14} {cn} "
              f"col {cur.get('collected')}→{target_col} rev {cur.get('revenue')}→{target_rev}")
        if not do_write:
            ok += 1
            continue
        p = httpx.patch(f"{URL}/rest/v1/consultation_cases",
                        params={"case_number": f"eq.{cn}"},
                        json={"collected": target_col, "revenue": target_rev},
                        headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"},
                        timeout=30)
        if p.status_code in (200, 204):
            ok += 1
        else:
            print(f"    PATCH 失敗 {p.status_code}: {p.text[:160]}")
            miss += 1
    print(f"  → {ok} ok / {miss} 失敗\n")
    return miss == 0


def apply_monthly_stats(credits, do_write, force):
    print("[B] monthly_stats（加性，marker 擋重跑）")
    if MARKER.exists() and not force:
        print(f"  marker 已存在（{MARKER.name}），跳過以免重複加。要重套用加 --force-monthly\n")
        return True
    by_month = defaultdict(float)
    for c in credits:
        by_month[(c["lawyer_id"], c["month"])] += c["add_amount"]
    ok = miss = 0
    for (lid, month), add in sorted(by_month.items(), key=lambda kv: -kv[1]):
        add = int(round(add))
        r = httpx.get(f"{URL}/rest/v1/monthly_stats",
                      params={"lawyer_id": f"eq.{lid}", "month": f"eq.{month}",
                              "select": "collected,revenue"},
                      headers=HDR, timeout=30)
        r.raise_for_status()
        found = r.json()
        if not found:
            print(f"  ✗ 無 monthly_stats 列 ({lid[:8]}, {month})，credit {add} 將於下次 daily_update 補上")
            miss += 1
            continue
        cur = found[0]
        tcol = (cur.get("collected") or 0) + add
        trev = (cur.get("revenue") or 0) + add
        print(f"  ({lid[:8]}, {month}) +{add:>8,}  col {cur.get('collected')}→{tcol}")
        if not do_write:
            ok += 1
            continue
        p = httpx.patch(f"{URL}/rest/v1/monthly_stats",
                        params={"lawyer_id": f"eq.{lid}", "month": f"eq.{month}"},
                        json={"collected": tcol, "revenue": trev},
                        headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"},
                        timeout=30)
        if p.status_code in (200, 204):
            ok += 1
        else:
            print(f"    PATCH 失敗 {p.status_code}: {p.text[:160]}")
            miss += 1
    print(f"  → {ok} ok / {miss} 失敗或無列")
    if do_write and miss == 0:
        MARKER.write_text(json.dumps({
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "total": sum(by_month.values()), "buckets": len(by_month),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  寫入 marker：{MARKER.name}")
    print()
    return miss == 0


def revert(credits, do_write):
    """還原成 base：consultation_cases 設回 base_collected/base_revenue（絕對）；
    monthly_stats 減掉 marker 記錄的 per-bucket credit；刪 marker。"""
    print("[REVERT] consultation_cases → base（絕對）")
    for c in credits:
        cn = c["case_number"]
        bcol = int(round(c["base_collected"]))
        brev = int(round(c["base_revenue"]))
        print(f"  {c['lawyer']:<4}{c['client'][:14]:<14} {cn} → col {bcol} rev {brev}")
        if do_write:
            httpx.patch(f"{URL}/rest/v1/consultation_cases",
                        params={"case_number": f"eq.{cn}"},
                        json={"collected": bcol, "revenue": brev},
                        headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"},
                        timeout=30).raise_for_status()

    print("\n[REVERT] monthly_stats −= per-bucket credit")
    if not MARKER.exists():
        print("  無 marker → monthly_stats 未曾加 credit，跳過")
    else:
        by_month = defaultdict(float)
        for c in credits:
            by_month[(c["lawyer_id"], c["month"])] += c["add_amount"]
        for (lid, month), add in by_month.items():
            add = int(round(add))
            r = httpx.get(f"{URL}/rest/v1/monthly_stats",
                          params={"lawyer_id": f"eq.{lid}", "month": f"eq.{month}",
                                  "select": "collected,revenue"}, headers=HDR, timeout=30)
            r.raise_for_status()
            found = r.json()
            if not found:
                continue
            cur = found[0]
            tcol = (cur.get("collected") or 0) - add
            trev = (cur.get("revenue") or 0) - add
            print(f"  ({lid[:8]}, {month}) -{add:>8,}  col {cur.get('collected')}→{tcol}")
            if do_write:
                httpx.patch(f"{URL}/rest/v1/monthly_stats",
                            params={"lawyer_id": f"eq.{lid}", "month": f"eq.{month}"},
                            json={"collected": tcol, "revenue": trev},
                            headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"},
                            timeout=30).raise_for_status()
        if do_write:
            MARKER.unlink(missing_ok=True)
            print(f"  刪除 marker：{MARKER.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true",
                    help="把目前 credits 檔對應的 materialization 還原成 base")
    ap.add_argument("--force-monthly", action="store_true",
                    help="忽略 marker，強制重套用 monthly_stats 加性更新")
    args = ap.parse_args()

    credits = load_credits()
    print(f"credits: {len(credits)} 筆，合計 {sum(c['add_amount'] for c in credits):,.0f}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}{' (REVERT)' if args.revert else ''}\n")

    if args.revert:
        revert(credits, args.apply)
    else:
        apply_consultation_cases(credits, args.apply)
        apply_monthly_stats(credits, args.apply, args.force_monthly)

    if not args.apply:
        print("DRY-RUN：未寫 DB。確認無誤後加 --apply。")


if __name__ == "__main__":
    main()
