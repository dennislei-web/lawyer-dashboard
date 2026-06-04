"""講座報名 → 諮詢約成 轉化追蹤 → Supabase ETL
來源 Google Sheet「講座報名/後續處理」分頁 gid=438665286（客服團隊維護）

此分頁可公開 CSV 匯出，故直接用 urllib 抓 CSV，不需 Google service account。

欄位（第二列為表頭）：
  編號 / 填表時間 / 姓名 / Email / 電話 / 諮詢需求 / 聯繫管道 / line ID /
  方便聯繫時間 / 需要律師如何協助 / 利衝查詢日期 / 查詢時間 / 姓名查詢 /
  電話查詢 / 特殊狀況 / 負責同仁 / 聯繫狀況摘要 / 聯繫完成 / 利衝建檔 /
  導入line@ / 是否約成 / 預約資訊

每天 09:00 由 GitHub Action 全量 reload（先清空再 upsert）。

Usage:
  python sync_seminar.py          # 抓取 → 寫入 Supabase
  python sync_seminar.py --dry    # 只解析印出統計，不寫入
"""
from __future__ import annotations
import os, sys, csv, io, re, json
import urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import date

ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SHEET_ID = "1LCzLzUifrFNzukV243lriTcBIqMx7a4idJtbDEzdk-M"
GID = "438665286"
CSV_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
           f"/export?format=csv&gid={GID}")

DRY = "--dry" in sys.argv


def fetch_csv() -> list[list[str]]:
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8")
    return list(csv.reader(io.StringIO(raw)))


def cell(row, i):
    return row[i].strip() if i < len(row) and row[i] is not None else ""


def truthy(v: str) -> bool:
    return str(v).strip().upper() == "TRUE"


def clean(v: str) -> str:
    """壓縮多行/多餘逗號的儲存格（如複選的方便聯繫時間）。"""
    if not v:
        return ""
    parts = [p.strip().strip(",") for p in re.split(r"[\n]+", v)]
    parts = [p for p in parts if p]
    return " / ".join(parts)


def parse_reg_date(v: str):
    """'2026/5/28 0:0:0' → date(2026,5,28)。"""
    if not v:
        return None
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", v.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# 表頭欄位 → 索引（容錯：以表頭文字定位，而非寫死位置）
FIELD_HINTS = {
    "lead_no":        ["編號"],
    "reg_at":         ["填表時間"],
    "name":           ["姓名"],          # 「填單的姓名…」
    "email":          ["Email", "email", "信箱"],
    "phone":          ["電話"],          # 注意：避開「電話查詢」
    "has_need":       ["諮詢需求"],
    "contact_channel":["聯繫管道"],
    "line_id":        ["line ID", "line id"],
    "contact_time":   ["方便聯繫時間"],
    "help_needed":    ["如何協助"],
    "query_date":     ["查詢日期"],
    "name_query":     ["姓名查詢"],
    "phone_query":    ["電話查詢"],
    "special_status": ["特殊狀況"],
    "owner":          ["負責同仁"],
    "contact_notes":  ["聯繫狀況摘要"],
    "contacted":      ["聯繫完成"],
    "conflict_filed": ["利衝建檔"],
    "line_url":       ["導入line", "導入LINE"],
    "booked":         ["是否約成"],
    "booking_info":   ["預約資訊"],
}


def build_colmap(header: list[str]) -> dict:
    """回傳 field → column index。phone 須避開 phone_query（先定位 phone_query）。"""
    cols = {}
    # 先抓需要排他的欄位
    for i, h in enumerate(header):
        ht = (h or "").replace("\n", "")
        if "電話查詢" in ht and "phone_query" not in cols:
            cols["phone_query"] = i
    for field, hints in FIELD_HINTS.items():
        if field in cols:
            continue
        for i, h in enumerate(header):
            ht = (h or "").replace("\n", "")
            if i in cols.values():
                continue
            if field == "phone" and "查詢" in ht:
                continue
            if any(hint in ht for hint in hints):
                cols[field] = i
                break
    return cols


def parse_rows(rows: list[list[str]]) -> list[dict]:
    # 找表頭列（含「填表時間」者）
    hdr_i = next((i for i, r in enumerate(rows) if any("填表時間" in c for c in r)), None)
    if hdr_i is None:
        raise SystemExit("找不到表頭列（含『填表時間』）。")
    header = rows[hdr_i]
    cols = build_colmap(header)
    missing = [f for f in ("name", "reg_at", "booked", "conflict_filed") if f not in cols]
    if missing:
        raise SystemExit(f"表頭缺少欄位對應：{missing}；偵測到 {cols}")

    out = []
    seq = 0
    for ridx, r in enumerate(rows[hdr_i + 1:]):
        g = lambda f: cell(r, cols[f]) if f in cols else ""
        name = g("name")
        email = g("email")
        phone = g("phone")
        reg_at = g("reg_at")
        # 過濾空白佔位列（無姓名/email/電話/填表時間）
        if not any([name, email, phone, reg_at]):
            continue
        seq += 1
        lead_no = g("lead_no")
        out.append({
            "lead_key": lead_no or f"seq_{seq}",
            "lead_no": lead_no,
            "row_index": ridx,
            "reg_at": reg_at,
            "reg_date": parse_reg_date(reg_at),
            "name": name,
            "email": email,
            "phone": phone,
            "has_need": g("has_need") == "是",
            "contact_channel": clean(g("contact_channel")),
            "line_id": g("line_id"),
            "contact_time": clean(g("contact_time")),
            "help_needed": g("help_needed"),
            "query_date": g("query_date"),
            "name_query": g("name_query"),
            "phone_query": g("phone_query"),
            "special_status": g("special_status"),
            "owner": g("owner"),
            "contact_notes": g("contact_notes"),
            "contacted": truthy(g("contacted")),
            "conflict_filed": truthy(g("conflict_filed")),
            "line_url": g("line_url"),
            "booked": truthy(g("booked")),
            "booking_info": g("booking_info"),
        })
    # lead_key 去重保險
    seen, uniq = set(), []
    for row in out:
        k = row["lead_key"]
        if k in seen:
            k = f"{k}_{row['row_index']}"
            row["lead_key"] = k
        seen.add(k)
        uniq.append(row)
    return uniq


def supabase_replace(rows: list[dict]):
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    # DELETE all
    del_url = f"{url}/rest/v1/seminar_leads?lead_key=not.is.null"
    req = urllib.request.Request(del_url, method="DELETE",
                                 headers={**headers, "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(f"  [warn] delete: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
    if not rows:
        return 0
    params = urllib.parse.urlencode({"on_conflict": "lead_key"})
    post_url = f"{url}/rest/v1/seminar_leads?{params}"
    data = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(post_url, data=data, method="POST", headers={
        **headers, "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"upsert failed: {e.code} {e.read().decode()[:400]}")
    return len(rows)


def print_stats(rows: list[dict]):
    n = len(rows)
    cf = sum(1 for r in rows if r["conflict_filed"])
    ct = sum(1 for r in rows if r["contacted"])
    li = sum(1 for r in rows if r["line_url"])
    bk = sum(1 for r in rows if r["booked"])
    pct = lambda x: f"{x/n*100:.0f}%" if n else "—"
    print(f"報名 {n} → 利衝建檔 {cf} ({pct(cf)}) → 聯繫完成 {ct} ({pct(ct)}) "
          f"→ 導入LINE@ {li} ({pct(li)}) → 約成 {bk} ({pct(bk)})")
    owners = {}
    for r in rows:
        o = r["owner"] or "（未分派）"
        owners.setdefault(o, [0, 0, 0])
        owners[o][0] += 1
        owners[o][1] += 1 if r["contacted"] else 0
        owners[o][2] += 1 if r["booked"] else 0
    print("負責同仁：")
    for o, (tot, c, b) in sorted(owners.items(), key=lambda x: -x[1][0]):
        print(f"  {o}: 分派 {tot} / 已聯繫 {c} / 約成 {b}")


def main():
    rows = parse_rows(fetch_csv())
    print(f"解析出 {len(rows)} 筆線索")
    print_stats(rows)
    if DRY:
        print("[dry-run] 未寫入 Supabase")
        return
    n = supabase_replace(rows)
    print(f"✓ 已寫入 seminar_leads：{n} 筆")


if __name__ == "__main__":
    main()
