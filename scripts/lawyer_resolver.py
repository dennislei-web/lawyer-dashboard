"""
真正承辦律師判定 — 解決 CRM PM / 法務污染 assigned_lawyers 的問題

背景：
  CRM `assigned_lawyers` 欄位常被設成法務 PM 名字（如江欣柔在北所二部）。
  真正承辦律師在 `responsible_lawyer` 欄位。但有時 responsible_lawyer 空白，
  或裡面也含已離職的律師。
  本模組統一解析「這筆 record 真正歸屬哪個現職諮詢律師」。

API：
  resolve_real_lawyer(record_dict) → str   # 律師名；找不到回 "(無法判定)"
  is_consulting_name(name) → bool          # 是不是現職諮詢律師（不在排除清單）
  iter_consulting_names(s) → list[str]     # 從逗號字串解析並過濾掉非諮詢人員
"""
import re

# 非諮詢人員名單 — 對應 compute_lawyer_departments.py 的 NON_CONSULTING_LAWYER_IDS
# 來源：lawyers.role 為 legal_staff / 部分 manager / 部門帳號 / dummy admin
NON_CONSULTING_NAMES = {
    # 法務 (legal_staff)
    "謝依璇", "賴佳瑩", "曾靖雯", "董沐穎", "江欣柔", "黃逸庭",
    # 行政/管理
    "蘇思蓓",
    # 財務 (admin 但非諮詢)
    "張飛宇",
    # 部門帳號 / dummy
    "客戶關係部", "股東",
}


def _split(s):
    if not s: return []
    return [x.strip() for x in re.split(r"[,，、]\s*", s) if x.strip()]


def is_consulting_name(name):
    return bool(name) and name not in NON_CONSULTING_NAMES


def iter_consulting_names(s):
    """從逗號分隔字串解析名字並過濾掉非諮詢人員。"""
    return [n for n in _split(s) if is_consulting_name(n)]


def resolve_real_lawyer(record):
    """從 revenue_records 一筆記錄找出真正承辦律師。

    優先順序：
      1) responsible_lawyer 第一位現職諮詢律師
      2) assigned_lawyers 第一位現職諮詢律師
      3) responsible_lawyer 第一位（即使在排除清單，避免完全失蹤）
      4) "(無法判定)"

    回傳: str（律師名）
    """
    for field in ("responsible_lawyer", "assigned_lawyers"):
        names = _split(record.get(field) or "")
        for n in names:
            if is_consulting_name(n):
                return n
    # fallback：兩個欄位都沒有現職諮詢律師（可能是離職律師舊案）
    for field in ("responsible_lawyer", "assigned_lawyers"):
        names = _split(record.get(field) or "")
        if names:
            return names[0] + "*"  # 後綴 * 標記為離職/排除清單
    return "(無法判定)"
