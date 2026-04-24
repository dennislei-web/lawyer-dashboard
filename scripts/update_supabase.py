"""
update_supabase.py
讀取 consultation_all_data.xlsx，計算每位律師的月統計，upsert 到 Supabase。

使用方式：
  python update_supabase.py                          # 處理所有月份
  python update_supabase.py --month 2026-03          # 只處理指定月份
  python update_supabase.py --xlsx path/to/file.xlsx # 指定 xlsx 路徑

環境變數（或 .env）：
  SUPABASE_URL=https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
"""

import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role key, 繞過 RLS

DEFAULT_XLSX = "consultation_all_data.xlsx"


def load_xlsx(path: str) -> pd.DataFrame:
    """讀取 xlsx 並標準化欄位名稱。"""
    df = pd.read_excel(path)
    # 移除欄位前後空白
    df.columns = df.columns.str.strip()
    return df


def compute_monthly_stats(df: pd.DataFrame, month: str | None = None) -> pd.DataFrame:
    """
    計算每位律師每月統計。

    篩選規則：
    - 排除「是否列入計算」為「否」的記錄
    - 簽約狀態含「未」或空白 → 未簽約
    """
    # 排除不列入計算的記錄
    if "是否列入計算" in df.columns:
        df = df[df["是否列入計算"].astype(str).str.strip() != "否"].copy()

    # 解析日期並提取月份
    df["諮詢日期"] = pd.to_datetime(df["諮詢日期"], errors="coerce")
    df = df.dropna(subset=["諮詢日期"])
    df["month"] = df["諮詢日期"].dt.strftime("%Y-%m")

    if month:
        df = df[df["month"] == month]

    if df.empty:
        print("沒有符合條件的資料")
        return pd.DataFrame()

    # 判斷是否簽約
    def is_signed(status):
        s = str(status).strip()
        if s == "" or s == "nan" or "未" in s:
            return False
        return True

    df["已簽約"] = df["簽約狀態"].apply(is_signed)

    # 數值欄位 fuzzy 匹配（xlsx 欄位名可能含括號註解，例如「應收金額（案件委任金）」）
    rev_col = next((c for c in df.columns if "應收" in c), None)
    col_col = next((c for c in df.columns if "已收" in c), None)
    df["revenue"] = (
        pd.to_numeric(df[rev_col].astype(str).str.replace(",", "").str.strip(), errors="coerce").fillna(0)
        if rev_col else 0
    )
    df["collected"] = (
        pd.to_numeric(df[col_col].astype(str).str.replace(",", "").str.strip(), errors="coerce").fillna(0)
        if col_col else 0
    )

    # 按律師+月份分組
    grouped = df.groupby(["諮詢律師", "month"]).agg(
        consult_count=("諮詢律師", "count"),
        signed_count=("已簽約", "sum"),
        revenue=("revenue", "sum"),
        collected=("collected", "sum"),
    ).reset_index()

    grouped["signed_count"] = grouped["signed_count"].astype(int)
    grouped["sign_rate"] = (
        grouped["signed_count"] / grouped["consult_count"] * 100
    ).round(2)

    return grouped


def get_lawyer_id_map(supabase) -> dict[str, str]:
    """取得律師名稱 → ID 的對照表。"""
    resp = supabase.table("lawyers").select("id, name").execute()
    return {row["name"]: row["id"] for row in resp.data}


def upsert_monthly_stats(supabase, stats: pd.DataFrame, lawyer_map: dict[str, str]):
    """把月統計 upsert 到 Supabase。"""
    rows = []
    skipped = []

    for _, row in stats.iterrows():
        lawyer_name = row["諮詢律師"]
        lawyer_id = lawyer_map.get(lawyer_name)

        if not lawyer_id:
            skipped.append(lawyer_name)
            continue

        rows.append({
            "lawyer_id": lawyer_id,
            "month": row["month"],
            "consult_count": int(row["consult_count"]),
            "signed_count": int(row["signed_count"]),
            "sign_rate": float(row["sign_rate"]),
            "revenue": int(row["revenue"]),
            "collected": int(row["collected"]),
        })

    if skipped:
        unique_skipped = sorted(set(skipped))
        print(f"⚠ 找不到對應律師，已跳過：{', '.join(unique_skipped)}")
        print("  請確認 Supabase lawyers 表中有這些律師的資料")

    if rows:
        # upsert by (lawyer_id, month) unique constraint
        resp = supabase.table("monthly_stats").upsert(
            rows, on_conflict="lawyer_id,month"
        ).execute()
        print(f"✓ 成功 upsert {len(rows)} 筆月統計")
    else:
        print("沒有資料需要更新")


def upsert_consultation_logs(supabase, df: pd.DataFrame, lawyer_map: dict[str, str]):
    """把逐筆諮詢記錄 upsert 到 Supabase（選配功能）。"""
    if "是否列入計算" in df.columns:
        df = df[df["是否列入計算"].astype(str).str.strip() != "否"].copy()

    # fuzzy 匹配金額欄位（容忍「應收金額（案件委任金）」等帶註解的欄位名）
    rev_col = next((c for c in df.columns if "應收" in c), None)
    col_col = next((c for c in df.columns if "已收" in c), None)

    rows = []
    for _, row in df.iterrows():
        lawyer_name = str(row.get("諮詢律師", "")).strip()
        lawyer_id = lawyer_map.get(lawyer_name)
        if not lawyer_id:
            continue

        case_number = str(row.get("案件編號", "")).strip()
        if not case_number or case_number == "nan":
            continue

        consult_date = pd.to_datetime(row.get("諮詢日期"), errors="coerce")
        if pd.isna(consult_date):
            continue

        sign_status = str(row.get("簽約狀態", "")).strip()
        if sign_status == "nan":
            sign_status = ""

        rows.append({
            "lawyer_id": lawyer_id,
            "case_number": case_number,
            "consult_date": consult_date.strftime("%Y-%m-%d"),
            "office": str(row.get("接案所", "")).strip(),
            "brand": str(row.get("品牌", "")).strip(),
            "client_name": str(row.get("當事人", "")).strip(),
            "consult_method": str(row.get("諮詢方式", "")).strip(),
            "service_type": str(row.get("服務項目", "")).strip(),
            "sign_status": sign_status,
            "revenue": int(pd.to_numeric(row.get(rev_col, 0) if rev_col else 0, errors="coerce") or 0),
            "collected": int(pd.to_numeric(row.get(col_col, 0) if col_col else 0, errors="coerce") or 0),
            "is_counted": str(row.get("是否列入計算", "")).strip() != "否",
        })

    if rows:
        # 分批 upsert，每批 500 筆
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            supabase.table("consultation_logs").upsert(
                batch, on_conflict="case_number"
            ).execute()
        print(f"✓ 成功 upsert {len(rows)} 筆諮詢記錄")


def main():
    parser = argparse.ArgumentParser(description="更新 Supabase 諮詢統計資料")
    parser.add_argument("--xlsx", default=DEFAULT_XLSX, help="xlsx 檔案路徑")
    parser.add_argument("--month", default=None, help="指定月份 (格式: 2026-03)")
    parser.add_argument("--with-logs", action="store_true", help="同時更新逐筆諮詢記錄")
    args = parser.parse_args()

    if not os.path.exists(args.xlsx):
        print(f"✗ 找不到檔案：{args.xlsx}")
        sys.exit(1)

    print(f"讀取 {args.xlsx} ...")
    df = load_xlsx(args.xlsx)
    print(f"  共 {len(df)} 筆記錄")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    lawyer_map = get_lawyer_id_map(supabase)
    print(f"  Supabase 中有 {len(lawyer_map)} 位律師")

    print("計算月統計 ...")
    stats = compute_monthly_stats(df.copy(), args.month)
    if not stats.empty:
        upsert_monthly_stats(supabase, stats, lawyer_map)

    if args.with_logs:
        print("更新逐筆諮詢記錄 ...")
        upsert_consultation_logs(supabase, df, lawyer_map)

    print("完成！")


if __name__ == "__main__":
    main()
