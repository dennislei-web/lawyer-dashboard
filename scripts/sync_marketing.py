"""雷律師 廣告/LINE 成效 → Supabase ETL
來源 Google Sheet「喆律 - 雷律師 ｜預算｜成效」(welly 維護，每天自動從 FB 更新)

Pull (全量 reload):
- 「上線至今」cols A-G  → mkt_monthly   (月成效表)
- 「上線至今」cols I-P  → mkt_biweekly  (雙周 LINE@ 成長表)
- 「雙周報」週報回覆文字 → mkt_appointments (月約訪場次，容錯解析)

Usage:  python sync_marketing.py
"""
from __future__ import annotations
import os, sys, re, json
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

import httplib2, google_auth_httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

SHEET_ID = "1jOPDh0LeyihRwt0Q403q9UWbHLImc-1BoHRE4z_YEas"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def _load_credentials():
    raw = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and Path(path).exists():
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit("Google credentials missing (GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS).")


creds = _load_credentials()


def get_range(rng, render="UNFORMATTED_VALUE"):
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=120))
    svc = build("sheets", "v4", http=http, cache_discovery=False).spreadsheets()
    last = None
    for attempt in range(3):
        try:
            return svc.values().get(spreadsheetId=SHEET_ID, range=rng,
                                    valueRenderOption=render,
                                    dateTimeRenderOption="FORMATTED_STRING").execute().get("values", [])
        except Exception as e:
            last = e
            print(f"  retry {attempt+1}/3 {rng[:40]}: {type(e).__name__}", file=sys.stderr)
    raise last


def to_num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).replace(",", "").replace("NT$", "").replace("$", "").strip()
    if not s or s == "-": return None
    try: return float(s)
    except Exception: return None


def to_int(v):
    n = to_num(v)
    return int(round(n)) if n is not None else None


def cell(row, i):
    return row[i] if i < len(row) else ""


def infer_year(month: int) -> int:
    """campaign 2025/08 起：8-12 月歸 2025，1-7 月歸 2026。"""
    return 2025 if month >= 8 else 2026


def parse_period_end(period: str):
    """'5/13-5/28(10:00)' → date(2026,5,28)；'8/1-9/23' → date(2025,9,23)。"""
    if not period: return None
    tail = period.split("-")[-1]
    tail = re.sub(r"\(.*?\)", "", tail).strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})", tail)
    if not m: return None
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        return date(infer_year(mo), mo, d).isoformat()
    except ValueError:
        return None


def supabase_replace(table, rows, conflict):
    """先清空再 upsert（全量 reload）。"""
    # DELETE all
    url = f"{SUPABASE_URL}/rest/v1/{table}?{conflict}=not.is.null"
    req = urllib.request.Request(url, method="DELETE", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(f"  [warn] delete {table}: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
    if not rows:
        return 0
    params = urllib.parse.urlencode({"on_conflict": conflict})
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    data = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"upsert {table} failed: {e.code} {e.read().decode()[:400]}")
    return len(rows)


# ============================================================
# 1) 月成效表 (上線至今 cols A-G)
# ============================================================
def build_monthly():
    vals = get_range("'上線至今'!A1:G30")
    rows = []
    for r in vals:
        mo = str(cell(r, 0)).strip()
        if not re.match(r"^\d{4}/\d{1,2}$", mo):
            continue
        rows.append({
            "month": mo,
            "total_spend": to_num(cell(r, 1)),
            "lead_spend": to_num(cell(r, 2)),
            "leads": to_int(cell(r, 3)),
            "cpl": to_num(cell(r, 4)),
            "line_link_spend": to_num(cell(r, 5)),
            "line_link_clicks": to_int(cell(r, 6)),
        })
    return rows


# ============================================================
# 2) 雙周 LINE@ 成長表 (上線至今 cols I-P = idx 8-15)
# ============================================================
def build_biweekly():
    vals = get_range("'上線至今'!I1:P40")
    rows = []
    for r in vals:
        period = str(cell(r, 0)).strip()  # I → idx0 of this range
        # I=period(0) J=contacted(1) K=cpl(2) L=line_added(3) M=line_total(4) N=line_cpa(5) O=appts(6) P=appt_cpa(7)
        if not re.match(r"^\d{1,2}/\d{1,2}", period):
            continue
        rows.append({
            "period": period,
            "period_end": parse_period_end(period),
            "contacted": to_int(cell(r, 1)),
            "cpl": to_num(cell(r, 2)),
            "line_added": to_int(cell(r, 3)),
            "line_total": to_int(cell(r, 4)),
            "line_cpa": to_num(cell(r, 5)),
            "appts_closed": to_int(cell(r, 6)),
            "appt_cpa": to_num(cell(r, 7)),
        })
    return rows


# ============================================================
# 3) 月約訪場次 (雙周報 週報回覆文字，容錯解析)
#    文字內含「實際約訪記錄 10月 10 場。11月 5場。… 5月 5場」
# ============================================================
def build_appointments():
    vals = get_range("'雙周報'!B1:B60", render="FORMATTED_VALUE")
    appts = {}
    for r in vals:
        text = cell(r, 0)
        if not text or "場" not in str(text):
            continue
        # 取「實際約訪記錄」段落後的內容；抓所有「N月 M場」
        for mo, cnt in re.findall(r"(\d{1,2})\s*月\s*(\d{1,2})\s*場", str(text)):
            mo, cnt = int(mo), int(cnt)
            if 1 <= mo <= 12:
                key = f"{infer_year(mo)}-{mo:02d}"
                # 取最大值（最新一段文字通常最完整；同月以最大為準避免被舊段覆蓋成更小）
                appts[key] = max(appts.get(key, 0), cnt) if key in appts else cnt
        # 第一個含「場」的(最上面=最新)區塊解析完就停，避免舊區塊干擾
        if appts:
            break
    return [{"month": k, "appointments": v} for k, v in sorted(appts.items())]


def main():
    monthly = build_monthly()
    biweekly = build_biweekly()
    appts = build_appointments()

    n1 = supabase_replace("mkt_monthly", monthly, "month")
    n2 = supabase_replace("mkt_biweekly", biweekly, "period")
    n3 = supabase_replace("mkt_appointments", appts, "month")

    print(f"✓ mkt_monthly      {n1} 列  (月份 {monthly[0]['month'] if monthly else '—'} → {monthly[-1]['month'] if monthly else '—'})")
    print(f"✓ mkt_biweekly     {n2} 列  (最新 {biweekly[-1]['period'] if biweekly else '—'}, 累計LINE {biweekly[-1]['line_total'] if biweekly else '—'})")
    print(f"✓ mkt_appointments {n3} 列  {[(a['month'], a['appointments']) for a in appts]}")


if __name__ == "__main__":
    main()
