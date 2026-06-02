"""里長開發記錄表 → Supabase ETL

來源：Google Sheet「里長開發記錄表」(6 分頁 = 6 位負責同仁，欄位格式不一)
策略：
- 逐分頁找表頭(col0 == 里/里別)，用「欄位名稱」容錯對齊到 canonical schema
- 第一/二/三次拜訪日 後面的「紀錄」依出現順序配對
- 文宣放置地點(桌牌/小文宣/海報/里長辦公室/里民服務中心/里民告示欄)用子表頭對齊
- 整列原文存 raw(jsonb)備援
- 全量 reload(先清空 bd_li_outreach 再 insert)

Usage:  python sync_li_outreach.py
"""
from __future__ import annotations
import os, sys, json
import urllib.request, urllib.parse, urllib.error
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import httplib2, google_auth_httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

SHEET_ID = "1ADNyDr_JibT1mGDcd4sbvcClQMpuogD1UvEO-_c5VJ8"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TABLE = "bd_li_outreach"


def _load_credentials():
    raw = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and Path(path).exists():
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit("Google credentials missing (GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS)")


creds = _load_credentials()


def sheets():
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=180))
    return build("sheets", "v4", http=http, cache_discovery=False).spreadsheets()


# ── value helpers ──
def clean(v):
    return str(v).strip() if v is not None else ""


def to_bool(v):
    s = clean(v).upper()
    if s in ("TRUE", "是", "V", "✓", "YES", "Y"):
        return True
    if s in ("FALSE", "否", "", "X", "NO", "N"):
        return False if s == "FALSE" else (False if s in ("否", "X", "NO", "N") else None)
    return None


def b(v):
    """嚴格 TRUE/FALSE 欄位 → bool/None"""
    s = clean(v).upper()
    if s == "TRUE":
        return True
    if s == "FALSE":
        return False
    return None


# canonical 欄位 ← 可能的表頭名稱
ALIAS = {
    "region": ["里", "里別"],
    "chief": ["里長", "里長姓名"],
    "chief_phone": ["連絡電話", "聯絡電話", "手機", "電話"],
    "chief_address": ["里長辦公室地址", "地址"],
    "social": ["社群經營", "社群"],
    "expected_contact": ["預計聯繫時間"],
    "visit_result": ["拜訪結果"],
    "tier": ["維繫分級"],
    "talked": ["完成洽談"],
    "adopted": ["是否採用"],
    "pulled_group": ["拉里長群組"],
    "joined_community": ["加入里社群"],
    "flyer_placed": ["是否完成放置文宣"],
    "flyer_deskcard": ["桌牌"],
    "flyer_small": ["小文宣"],
    "flyer_poster": ["海報"],
    "loc_office": ["里長辦公室"],
    "loc_service": ["里民服務中心"],
    "loc_board": ["里民告示欄"],
    "tracking": ["追蹤與否"],
    "note": ["其餘註記", "備註"],
}
NAME2CANON = {name: canon for canon, names in ALIAS.items() for name in names}
BOOL_FIELDS = {"talked", "adopted", "pulled_group", "joined_community", "flyer_placed",
               "flyer_deskcard", "flyer_small", "flyer_poster", "loc_office", "loc_service", "loc_board"}


def build_colmap(header, subheader):
    """回傳 {canonical: col_index} 與 visit 配對。
    effective header = 表頭非空則用表頭，否則用子表頭(處理文宣放置地點群組)。"""
    n = max(len(header), len(subheader))
    eff = []
    for i in range(n):
        h = clean(header[i]) if i < len(header) else ""
        s = clean(subheader[i]) if i < len(subheader) else ""
        eff.append(h if h else s)

    colmap = {}
    visits = {}  # visit_no -> {date: idx, note: idx}
    last_visit = None
    for i, name in enumerate(eff):
        if not name:
            continue
        # 拜訪日 / 紀錄 依順序配對
        for vno, key in ((1, "第一次拜訪日"), (2, "第二次拜訪日"), (3, "第三次拜訪日")):
            if name == key:
                visits.setdefault(vno, {})["date"] = i
                last_visit = vno
        if name == "紀錄" and last_visit:
            visits.setdefault(last_visit, {})["note"] = i
            last_visit = None  # 一個拜訪日只配一個紀錄
            continue
        canon = NAME2CANON.get(name)
        if canon and canon not in colmap:
            colmap[canon] = i
    return colmap, visits


def find_header_row(rows):
    for i, r in enumerate(rows[:6]):
        if r and clean(r[0]) in ("里", "里別"):
            return i
    return None


def parse_tab(svc, title):
    rows = svc.values().get(
        spreadsheetId=SHEET_ID, range=f"'{title}'!A1:AG3000",
        valueRenderOption="FORMATTED_VALUE", dateTimeRenderOption="FORMATTED_STRING",
    ).execute().get("values", [])
    h = find_header_row(rows)
    if h is None:
        print(f"  ⚠ {title}: 找不到表頭，跳過", file=sys.stderr)
        return []
    header = rows[h]
    subheader = rows[h + 1] if h + 1 < len(rows) else []
    colmap, visits = build_colmap(header, subheader)
    # 資料列從子表頭之後開始(子表頭那列若含 桌牌/海報 等才跳過)
    sub_is_header = any(clean(c) in ("桌牌", "小文宣", "海報", "里長辦公室", "里民服務中心", "里民告示欄") for c in subheader)
    data_start = h + 2 if sub_is_header else h + 1

    def cell(r, idx):
        return clean(r[idx]) if (idx is not None and idx < len(r)) else ""

    out = []
    for ri in range(data_start, len(rows)):
        r = rows[ri]
        if not r:
            continue
        region = cell(r, colmap.get("region"))
        chief = cell(r, colmap.get("chief"))
        if not region and not chief:
            continue
        rec = {"owner": title, "row_index": ri + 1, "raw": {}}
        # raw：整列 header→value
        for i, c in enumerate(r):
            hn = clean(header[i]) if i < len(header) else ""
            if hn and clean(c):
                rec["raw"][f"{i}:{hn}"] = clean(c)
        # canonical 欄位
        for canon, idx in colmap.items():
            val = cell(r, idx)
            if canon in BOOL_FIELDS:
                rec[canon] = b(val)
            else:
                rec[canon] = val or None
        # visits
        for vno, m in visits.items():
            rec[f"visit{vno}_date"] = cell(r, m.get("date")) or None
            rec[f"visit{vno}_note"] = cell(r, m.get("note")) or None
        out.append(rec)
    return out


# ── Supabase ──
def supa_delete_all():
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?id=gt.0"
    req = urllib.request.Request(url, method="DELETE", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()


COLUMNS = ["owner", "region", "chief", "chief_phone", "chief_address", "social",
           "expected_contact", "visit1_date", "visit1_note", "visit2_date", "visit2_note",
           "visit3_date", "visit3_note", "visit_result", "tier", "talked", "adopted",
           "pulled_group", "joined_community", "flyer_placed", "flyer_deskcard", "flyer_small",
           "flyer_poster", "loc_office", "loc_service", "loc_board", "tracking", "note",
           "raw", "row_index"]


def normalize(rows):
    """PostgREST 批次 insert 要求每個 object key 一致 → 補齊所有欄位。"""
    return [{c: r.get(c) for c in COLUMNS} for r in rows]


def supa_insert(rows):
    rows = normalize(rows)
    CHUNK = 500
    done = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
        data = json.dumps(chunk, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json", "Prefer": "return=minimal",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
        except urllib.error.HTTPError as e:
            print(f"  ERR insert chunk {i//CHUNK}: {e.code} {e.read().decode('utf-8')[:400]}", file=sys.stderr)
            raise
        done += len(chunk)
        print(f"  insert {done}/{len(rows)}")
    return done


def main():
    svc = sheets()
    meta = svc.get(spreadsheetId=SHEET_ID, fields="sheets.properties.title").execute()
    tabs = [s["properties"]["title"] for s in meta["sheets"]]
    print(f"分頁: {tabs}")
    all_rows = []
    for t in tabs:
        recs = parse_tab(svc, t)
        adopted = sum(1 for r in recs if r.get("adopted"))
        print(f"  {t}: {len(recs)} 列 (採用 {adopted})")
        all_rows.extend(recs)
    print(f"總計 {len(all_rows)} 列 → reload {TABLE}")
    supa_delete_all()
    supa_insert(all_rows)
    print("✓ done")


if __name__ == "__main__":
    main()
