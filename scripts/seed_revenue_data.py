"""
seed_revenue_data.py
建立營運儀表板的範例資料（departments, department_members, revenue_records）。

使用方式：
  python scripts/seed_revenue_data.py

環境變數（或 .env）：
  SUPABASE_URL=https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
"""

import json
import os
import random
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
REST_URL = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def sb_post(table, data):
    """Insert rows via Supabase REST API."""
    r = requests.post(f"{REST_URL}/{table}", headers=HEADERS, json=data)
    r.raise_for_status()
    return r.json()


def sb_upsert(table, data, on_conflict):
    """Upsert rows via Supabase REST API."""
    h = {**HEADERS, "Prefer": "return=representation,resolution=merge-duplicates"}
    r = requests.post(f"{REST_URL}/{table}?on_conflict={on_conflict}", headers=h, json=data)
    r.raise_for_status()
    return r.json()


def sb_get(table, params=None):
    """Select rows via Supabase REST API."""
    h = {**HEADERS, "Prefer": ""}
    r = requests.get(f"{REST_URL}/{table}", headers=h, params=params or {})
    r.raise_for_status()
    return r.json()


# ─── 設定 ───────────────────────────────────────────────────
DEPARTMENTS = ["訴訟部", "非訟部", "顧問部"]

SOURCE_CHANNELS = ["網路", "推薦", "廣告", "法扶", "自來客", "合作夥伴"]

CASE_TYPES = [
    "民事訴訟", "刑事辯護", "家事案件", "勞資爭議",
    "公司設立", "契約審閱", "智財權", "不動產",
    "企業顧問", "法律諮詢", "遺產繼承", "債務協商",
]

LAST_NAMES = ["陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊"]
FIRST_NAMES = ["志明", "淑芬", "建宏", "美玲", "俊傑", "雅婷", "宗翰", "怡君", "家豪", "佳蓉"]


def random_name():
    return random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)


def main():
    print("=== 營運儀表板 - 範例資料匯入 ===\n")

    # 1. 建立部門
    print("1. 建立部門...")
    dept_ids = {}
    for name in DEPARTMENTS:
        result = sb_upsert("departments", {"name": name}, "name")
        dept_ids[name] = result[0]["id"]
        print(f"   ✓ {name} ({dept_ids[name][:8]}...)")

    # 2. 取得現有律師
    print("\n2. 取得現有律師...")
    lawyers = sb_get("lawyers", {"select": "id,name", "is_active": "eq.true"})
    print(f"   找到 {len(lawyers)} 位律師")

    if len(lawyers) < 3:
        print("   ⚠ 律師數量不足，跳過部門成員分配")
    else:
        # 3. 分配律師到部門
        print("\n3. 分配律師到部門...")
        random.shuffle(lawyers)
        chunk_size = max(1, len(lawyers) // len(DEPARTMENTS))

        for i, dept_name in enumerate(DEPARTMENTS):
            start = i * chunk_size
            end = start + chunk_size if i < len(DEPARTMENTS) - 1 else len(lawyers)
            dept_lawyers = lawyers[start:end]

            for j, lawyer in enumerate(dept_lawyers):
                role = "manager" if j == 0 else "member"
                sb_upsert("department_members", {
                    "department_id": dept_ids[dept_name],
                    "lawyer_id": lawyer["id"],
                    "role": role,
                }, "department_id,lawyer_id")

            manager = dept_lawyers[0]["name"] if dept_lawyers else "N/A"
            print(f"   ✓ {dept_name}: {len(dept_lawyers)} 人 (主管: {manager})")

    # 4. 產生範例營收記錄
    print("\n4. 產生範例營收記錄...")
    records = []
    today = date.today()

    for month in range(1, today.month + 1):
        month_start = date(today.year, month, 1)
        if month == 12:
            month_end = date(today.year, 12, 31)
        else:
            month_end = date(today.year, month + 1, 1) - timedelta(days=1)

        if month_end > today:
            month_end = today

        for dept_name in DEPARTMENTS:
            n_cases = random.randint(8, 15)

            for _ in range(n_cases):
                record_date = month_start + timedelta(
                    days=random.randint(0, (month_end - month_start).days)
                )
                revenue = random.choice([30000, 50000, 80000, 100000, 150000, 200000, 300000, 500000])
                is_refund = random.random() < 0.08
                collected_pct = random.choice([0, 0.3, 0.5, 0.7, 1.0])

                record = {
                    "record_date": record_date.isoformat(),
                    "department_id": dept_ids[dept_name],
                    "lawyer_id": random.choice(lawyers)["id"] if lawyers else None,
                    "case_number": f"REV-{today.year}{month:02d}-{random.randint(1000,9999)}",
                    "client_name": random_name(),
                    "case_type": random.choice(CASE_TYPES),
                    "source_channel": random.choice(SOURCE_CHANNELS),
                    "revenue": revenue,
                    "collected": int(revenue * collected_pct) if not is_refund else 0,
                    "refund": revenue if is_refund else 0,
                    "status": "退款處理" if is_refund else random.choice(["進行中", "已完成", "已結案"]),
                }
                records.append(record)

    # Batch insert (50 per batch)
    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        sb_post("revenue_records", batch)
        print(f"   已匯入 {min(i + batch_size, len(records))}/{len(records)} 筆")

    # 5. 計算月度統計
    print("\n5. 計算月度統計...")
    for month in range(1, today.month + 1):
        month_str = f"{today.year}-{month:02d}"
        for dept_name in DEPARTMENTS:
            dept_records = [
                r for r in records
                if r["department_id"] == dept_ids[dept_name]
                and r["record_date"].startswith(month_str)
            ]
            if not dept_records:
                continue

            stats = {
                "month": month_str,
                "department_id": dept_ids[dept_name],
                "total_revenue": sum(r["revenue"] for r in dept_records),
                "total_collected": sum(r["collected"] for r in dept_records),
                "total_refund": sum(r["refund"] for r in dept_records),
                "case_count": len(dept_records),
                "new_case_count": len(dept_records),
            }
            sb_upsert("monthly_revenue_stats", stats, "month,department_id")

        print(f"   ✓ {month_str}")

    print(f"\n=== 完成！共匯入 {len(records)} 筆營收記錄 ===")


if __name__ == "__main__":
    main()
