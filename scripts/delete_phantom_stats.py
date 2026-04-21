"""刪除 monthly_stats 裡的 pure phantom 列（consultation_cases 完全無對應的 lawyer+month）。

保守清理：只處理 13 筆「完全沒有 cases 對應」的幽靈列，不動有部分對應的列。
"""
import httpx, os, io, sys
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def get_all(path, **params):
    rows = []
    for offset in range(0, 50000, 1000):
        h = {**H, "Range-Unit": "items", "Range": f"{offset}-{offset+999}"}
        r = httpx.get(f"{URL}/rest/v1/{path}", params=params, headers=h, timeout=60)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows.extend(b)
        if len(b) < 1000:
            break
    return rows


def main():
    cases = get_all("consultation_cases", select="lawyer_id,case_date")
    case_keys = set()
    for c in cases:
        if c.get("case_date") and c.get("lawyer_id"):
            case_keys.add((c["lawyer_id"], c["case_date"][:7]))

    ms = get_all(
        "monthly_stats",
        select="lawyer_id,month,consult_count,signed_count,revenue,collected",
    )
    lawyers = httpx.get(
        f"{URL}/rest/v1/lawyers", params={"select": "id,name"}, headers=H, timeout=30
    ).json()
    names = {l["id"]: l["name"] for l in lawyers}

    phantoms = [m for m in ms if (m["lawyer_id"], m["month"]) not in case_keys]
    print(f"找到 {len(phantoms)} 筆 phantom，準備刪除:")
    for p in sorted(phantoms, key=lambda x: (names.get(x["lawyer_id"], ""), x["month"])):
        name = names.get(p["lawyer_id"], "?")
        print(
            f"  {name:<8} {p['month']}  consult={p['consult_count']} signed={p['signed_count']} collected=${p['collected']:,}"
        )

    print()
    success = 0
    for p in phantoms:
        r = httpx.delete(
            f"{URL}/rest/v1/monthly_stats",
            params={"lawyer_id": f"eq.{p['lawyer_id']}", "month": f"eq.{p['month']}"},
            headers={**H, "Prefer": "return=minimal"},
            timeout=30,
        )
        name = names.get(p["lawyer_id"], "?")
        if r.status_code in (200, 204):
            print(f"  ✓ deleted ({name}, {p['month']})")
            success += 1
        else:
            print(f"  ✗ FAILED ({name}, {p['month']}): {r.status_code} {r.text[:120]}")

    print(f"\n完成：成功刪除 {success}/{len(phantoms)} 筆")


if __name__ == "__main__":
    main()
