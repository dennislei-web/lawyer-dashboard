"""重算 monthly_stats，以 consultation_cases 為 source of truth。

政策：多律師諮詢只記第一位（consultation_cases 本來就這樣存）。
此腳本用於回溯修正既有的 phantom 資料（例如李家泓 2026-03 的 $150k）。

預設 dry-run。加 --apply 才會實際寫 DB。
"""
import httpx
import os
import io
import sys
import argparse
from dotenv import load_dotenv
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def get_all(path, **params):
    """Paginated GET."""
    ps = 1000
    rows = []
    for offset in range(0, 50 * ps, ps):
        h = {**HEADERS, "Range-Unit": "items", "Range": f"{offset}-{offset + ps - 1}"}
        r = httpx.get(f"{URL}/rest/v1/{path}", params=params, headers=h, timeout=60)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < ps:
            break
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="實際寫入 DB（不加就是 dry-run）")
    args = parser.parse_args()

    print("=" * 70)
    print(f"Mode: {'APPLY (will write DB)' if args.apply else 'DRY-RUN'}")
    print("=" * 70)

    # 1. Pull all consultation_cases with dates
    print("\n[1/4] 讀取所有 consultation_cases …")
    cases = get_all(
        "consultation_cases",
        select="lawyer_id,case_date,is_signed,revenue,collected",
        order="case_date.asc",
    )
    # Filter to rows with valid case_date and lawyer_id
    cases = [c for c in cases if c.get("case_date") and c.get("lawyer_id")]
    print(f"  有效 cases: {len(cases)}")

    # 2. Aggregate by (lawyer_id, month)
    print("\n[2/4] 重算 (lawyer_id, month) 聚合 …")
    agg = defaultdict(
        lambda: {"consult_count": 0, "signed_count": 0, "revenue": 0, "collected": 0}
    )
    for c in cases:
        key = (c["lawyer_id"], c["case_date"][:7])
        a = agg[key]
        a["consult_count"] += 1
        if c.get("is_signed"):
            a["signed_count"] += 1
        a["revenue"] += c.get("revenue") or 0
        a["collected"] += c.get("collected") or 0
    print(f"  預期 monthly_stats 筆數: {len(agg)}")

    # 3. Pull existing monthly_stats to compute diff
    print("\n[3/4] 讀取現有 monthly_stats …")
    existing = get_all(
        "monthly_stats",
        select="lawyer_id,month,consult_count,signed_count,revenue,collected",
    )
    existing_map = {
        (m["lawyer_id"], m["month"]): {
            "consult_count": m["consult_count"],
            "signed_count": m["signed_count"],
            "revenue": m["revenue"],
            "collected": m["collected"],
        }
        for m in existing
    }
    print(f"  現有 monthly_stats 筆數: {len(existing_map)}")

    # 4. Diff
    to_upsert = []
    to_delete = []
    unchanged = 0
    changed = []

    for key, new in agg.items():
        old = existing_map.get(key)
        sign_rate = round(100 * new["signed_count"] / new["consult_count"], 2) if new["consult_count"] else 0
        new_row = {
            "lawyer_id": key[0],
            "month": key[1],
            "consult_count": new["consult_count"],
            "signed_count": new["signed_count"],
            "sign_rate": sign_rate,
            "revenue": new["revenue"],
            "collected": new["collected"],
        }
        if old is None:
            to_upsert.append(new_row)
            changed.append(("NEW", key, None, new))
        elif (
            old["consult_count"] != new["consult_count"]
            or old["signed_count"] != new["signed_count"]
            or old["revenue"] != new["revenue"]
            or old["collected"] != new["collected"]
        ):
            to_upsert.append(new_row)
            changed.append(("UPDATE", key, old, new))
        else:
            unchanged += 1

    # Phantom rows: exist in monthly_stats but no cases at all for that (lawyer, month)
    for key in existing_map:
        if key not in agg:
            to_delete.append(key)
            changed.append(("DELETE", key, existing_map[key], None))

    print(f"\n[4/4] Diff 結果:")
    print(f"  未變動: {unchanged}")
    print(f"  需新增: {sum(1 for c in changed if c[0] == 'NEW')}")
    print(f"  需更新: {sum(1 for c in changed if c[0] == 'UPDATE')}")
    print(f"  需刪除（phantom）: {len(to_delete)}")

    # 5. Print changes
    # Resolve lawyer names for readability
    lawyers = httpx.get(f"{URL}/rest/v1/lawyers", params={"select": "id,name"}, headers=HEADERS, timeout=30).json()
    name_by_id = {l["id"]: l["name"] for l in lawyers}

    # Sort changes by abs(delta collected) desc
    def sort_key(c):
        action, _key, old, new = c
        if action == "NEW":
            return -abs(new["collected"])
        if action == "DELETE":
            return -abs(old["collected"])
        return -abs(new["collected"] - old["collected"])

    changed.sort(key=sort_key)

    print(f"\n前 30 大變動（以 collected 差額排序）:")
    print(f"{'action':<8}{'lawyer':<10}{'month':<10}{'old c/s/col':<24}{'new c/s/col':<24}")
    for action, key, old, new in changed[:30]:
        lname = name_by_id.get(key[0], key[0][:8])
        if action == "NEW":
            old_s = "(none)"
            new_s = f"{new['consult_count']}/{new['signed_count']}/${new['collected']:,}"
        elif action == "DELETE":
            old_s = f"{old['consult_count']}/{old['signed_count']}/${old['collected']:,}"
            new_s = "(delete)"
        else:
            old_s = f"{old['consult_count']}/{old['signed_count']}/${old['collected']:,}"
            new_s = f"{new['consult_count']}/{new['signed_count']}/${new['collected']:,}"
        print(f"{action:<8}{lname:<10}{key[1]:<10}{old_s:<24}{new_s:<24}")

    print()

    # 6. Apply (or print summary only)
    if not args.apply:
        print("=" * 70)
        print("DRY-RUN: 沒有寫 DB。確認無誤後加 --apply 實際執行。")
        print("=" * 70)
        return

    print("=" * 70)
    print("APPLY 模式，開始寫入 DB …")
    print("=" * 70)

    # Upserts in batches of 100
    upsert_headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    for i in range(0, len(to_upsert), 100):
        batch = to_upsert[i:i + 100]
        r = httpx.post(
            f"{URL}/rest/v1/monthly_stats?on_conflict=lawyer_id,month",
            json=batch,
            headers=upsert_headers,
            timeout=60,
        )
        if r.status_code not in (200, 201, 204):
            print(f"  upsert batch {i} 失敗: {r.status_code} {r.text[:200]}")
        else:
            print(f"  upsert batch {i}..{i+len(batch)-1} ok")

    # Deletes (phantom rows)
    for lawyer_id, month in to_delete:
        r = httpx.delete(
            f"{URL}/rest/v1/monthly_stats",
            params={"lawyer_id": f"eq.{lawyer_id}", "month": f"eq.{month}"},
            headers={**HEADERS, "Prefer": "return=minimal"},
            timeout=30,
        )
        if r.status_code not in (200, 204):
            print(f"  delete ({name_by_id.get(lawyer_id,lawyer_id[:8])}, {month}) 失敗: {r.status_code}")
        else:
            print(f"  deleted ({name_by_id.get(lawyer_id,lawyer_id[:8])}, {month})")

    print("\n完成。")


if __name__ == "__main__":
    main()
