"""里民方案約成諮詢場次 同步
來源：法律010總表 [10]總表，進線管道 含「里民」的列 → 按「轉線年份-轉線月份」彙總計數
寫入：bd_li_consults(month 'YYYY-MM', sessions, source='sheet')

口徑（雷皓明 2026-06-08 確認）：進線管道=里民服務（含「里民服務（電話）」）即一場約成諮詢。
每天 09:00 由 sync-li-outreach workflow 帶跑。無憑證自動跳過，不影響其他同步。

Usage:  python sync_li_consults.py
"""
from __future__ import annotations
import os, sys, json, time, urllib.request, urllib.error
from pathlib import Path
from collections import Counter

ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SHEET_ID = "1bGmKAFdCKZdfuag4tbGB7WeRxqBGFyJsvwDgbBpcZb4"
TAB = "總表"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TABLE = "bd_li_consults"

CRED = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
CRED_JSON = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

if not (CRED or CRED_JSON) or not SUPABASE_URL or not SUPABASE_KEY:
    print("缺 Google 憑證或 Supabase 設定 → 跳過約成諮詢場次同步(不影響其他同步)")
    sys.exit(0)

import httplib2, google_auth_httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

if CRED_JSON:  # CI：以 JSON 字串提供（與 sync_li_outreach 一致）
    creds = service_account.Credentials.from_service_account_info(
        json.loads(CRED_JSON), scopes=SCOPES)
else:          # 本機：檔案路徑
    creds = service_account.Credentials.from_service_account_file(CRED, scopes=SCOPES)


def _http():
    return google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=180))


def get_values(rng, render="FORMATTED_VALUE"):
    last = None
    for attempt in range(3):
        try:
            s = build("sheets", "v4", http=_http(), cache_discovery=False).spreadsheets()
            r = s.values().get(spreadsheetId=SHEET_ID, range=rng,
                               valueRenderOption=render,
                               dateTimeRenderOption="FORMATTED_STRING").execute()
            return r.get("values", [])
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def col_index(hdr, *substrs):
    for i, h in enumerate(hdr):
        for s in substrs:
            if s in (h or ""):
                return i
    return -1


def compute_monthly():
    hdr = get_values(f"{TAB}!A2:BG2")[0]          # 標頭在第 2 列（第 1 列是「填寫欄位」）
    c_ch = col_index(hdr, "進線管道")
    c_mon = col_index(hdr, "轉線月份")
    c_yr = col_index(hdr, "轉線年份")
    if min(c_ch, c_mon, c_yr) < 0:
        raise SystemExit(f"找不到必要欄位：進線管道={c_ch} 轉線月份={c_mon} 轉線年份={c_yr}")

    rows = get_values(f"{TAB}!A3:BG")
    counts = Counter()
    skipped = 0
    for r in rows:
        ch = (r[c_ch] if len(r) > c_ch else "") or ""
        if "里民" not in ch:
            continue
        y = (r[c_yr] if len(r) > c_yr else "") or ""
        m = (r[c_mon] if len(r) > c_mon else "") or ""
        try:
            key = f"{int(float(y))}-{int(float(m)):02d}"
        except (ValueError, TypeError):
            skipped += 1
            continue
        counts[key] += 1
    return counts, len(rows), skipped


def supa_upsert(rows):
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?on_conflict=month"
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()


def main():
    counts, total, skipped = compute_monthly()
    print(f"總表掃描 {total} 列；里民約成諮詢 {sum(counts.values())} 場，分佈：")
    for mo in sorted(counts):
        print(f"  {mo}: {counts[mo]}")
    if skipped:
        print(f"（{skipped} 筆里民列缺轉線年/月，未計入）", file=sys.stderr)

    payload = [{"month": mo, "sessions": n, "source": "sheet"} for mo, n in sorted(counts.items())]
    supa_upsert(payload)
    print(f"已 upsert {len(payload)} 個月份到 {TABLE}")


if __name__ == "__main__":
    main()
