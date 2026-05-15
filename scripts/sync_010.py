"""法律010總表 → Supabase ETL

Pull:
- 總表 [10] → raw_010_case
- 分期付款案件表 [4] → raw_010_installment_case
- 每週/月轉介律師目標案件數 [9] → raw_010_lawyer_target (monthly section only)

Then:
- Call rebuild_fact_010_monthly_team(year_from, year_to)
- Call rebuild_fact_010_monthly_lawyer(year_from, year_to)
- Print reconciliation report for given (year, month)

Usage:
  python sync_010.py [--reconcile-year YYYY --reconcile-month MM] [--year-from YYYY] [--year-to YYYY]
"""
from __future__ import annotations
import os, sys, json, hashlib, argparse
import urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime, date

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

SHEET_ID = "1bGmKAFdCKZdfuag4tbGB7WeRxqBGFyJsvwDgbBpcZb4"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def _load_credentials():
    """支援兩種模式:
    - GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON: raw JSON (CI / GH Actions)
    - GOOGLE_APPLICATION_CREDENTIALS: file path (local dev)
    """
    raw = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and Path(path).exists():
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit(
        "Google credentials missing. Set either:\n"
        "  GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON (raw JSON; CI)\n"
        "  GOOGLE_APPLICATION_CREDENTIALS (file path; local)"
    )


creds = _load_credentials()


def sheets():
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=180))
    return build("sheets", "v4", http=http, cache_discovery=False).spreadsheets()


def get_range(rng, render="UNFORMATTED_VALUE"):
    last = None
    for attempt in range(3):
        try:
            return sheets().values().get(
                spreadsheetId=SHEET_ID, range=rng,
                valueRenderOption=render,
                dateTimeRenderOption="FORMATTED_STRING",
            ).execute().get("values", [])
        except Exception as e:
            last = e
            print(f"  retry {attempt+1}/3 {rng[:50]}: {type(e).__name__}", file=sys.stderr)
    raise last


# ============================================================
# Helpers
# ============================================================

def to_bool(v):
    if v is None or v == "": return None
    s = str(v).strip()
    if s == "是": return True
    if s == "否": return False
    return None


def to_num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).replace(",", "").replace("NT$", "").replace("$", "").strip()
    if not s or s == "-": return None
    try: return float(s)
    except Exception: return None


def to_int(v):
    n = to_num(v)
    return int(n) if n is not None else None


def to_date(v):
    if v is None or v == "": return None
    s = str(v).strip()
    if not s: return None
    # 嘗試常見格式
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%-m/%-d"):
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: pass
    # 也試 民國: 114/05/01 (assume 民國 if year<200)
    try:
        parts = s.replace("-", "/").replace(".", "/").split("/")
        if len(parts) == 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 200: y += 1911  # 民國 → 西元
            return date(y, m, d).isoformat()
    except Exception:
        pass
    return None


def hash_key(*parts):
    s = "|".join(str(p) if p is not None else "" for p in parts)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def supabase_upsert(table, rows, on_conflict="case_key"):
    """Batch upsert via PostgREST (CHUNK=500)."""
    if not rows: return 0
    inserted = 0
    CHUNK = 500
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i+CHUNK]
        params = urllib.parse.urlencode({"on_conflict": on_conflict})
        url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
        data = json.dumps(chunk, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
            inserted += len(chunk)
            print(f"  upsert {table}: {inserted}/{len(rows)}")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")[:500]
            print(f"  ERR upserting {table} chunk {i//CHUNK}: {e.code} {err}", file=sys.stderr)
            raise
    return inserted


def supabase_rpc(fn, params=None):
    url = f"{SUPABASE_URL}/rest/v1/rpc/{fn}"
    data = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode("utf-8")


def supabase_query(table, **params):
    qs = urllib.parse.urlencode(params, safe="*().,")
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


# ============================================================
# Pull + parse: 總表 [10]
# ============================================================
# header row 2 cols (0-based):
#  0=A 010窗口 / 1=B 進線管道 / 2=C 地區 / 3=D 當事人 (PII) / 4=E 電話 (PII)
#  5=F 案件類型 / 6=G 案由 / 7=H 備註 / 8=I 接案律師
#  9=J 進線日期 / 10=K 轉線日期 / 11=L 追蹤日期 / 12=M 急案
# 13=N 轉線月 / 14=O 轉線年 / 15=P (spacer) / 16=Q 出席 / 17=R 未出席原因
# 18=S 會議日期 / 19=T 身分證 (PII) / 20=U 委任 / 21=V 委任金額
# 22=W 第一次收款金額 / 23=X 第一次收款日期 / 24=Y 備註 / 25=Z 分期期數
# 26=AA 未付金額 / 27=AB 第二期日 / 28=AC 第二期額 / ... AV/AW=第十二期
# 51=AZ 出席bin / 52=BA 委任bin / 53=BB 收款月 / 54=BC 收款年

INSTALL_COL_PAIRS = [(27, 28), (29, 30), (31, 32), (33, 34), (35, 36), (37, 38),
                     (39, 40), (41, 42), (43, 44), (45, 46), (47, 48)]  # 第二~十二期 in 總表


def parse_zonghyu_row(row, sheet_row_idx):
    if len(row) < 15: return None
    name = row[3] if len(row) > 3 else ""           # 當事人 - 用於 hash 不存
    intake_date = to_date(row[9] if len(row) > 9 else None)
    handling_lawyer = row[8] if len(row) > 8 else None
    if not name and not intake_date: return None  # 空 row

    case_key = hash_key(name, intake_date, handling_lawyer, sheet_row_idx)

    schedule = []
    for di, ai in INSTALL_COL_PAIRS:
        d = to_date(row[di]) if di < len(row) else None
        a = to_num(row[ai]) if ai < len(row) else None
        if d or a:
            schedule.append({"date": d, "amount": a})

    return {
        "case_key": case_key,
        "sheet_row": sheet_row_idx,
        "team_owner": (row[0] or None) if len(row) > 0 else None,
        "channel":    (row[1] or None) if len(row) > 1 else None,
        "region":     (row[2] or None) if len(row) > 2 else None,
        "case_type":  (row[5] or None) if len(row) > 5 else None,
        "case_reason":(row[6] or None) if len(row) > 6 else None,
        "handling_lawyer": handling_lawyer or None,
        "intake_date":     intake_date,
        "referral_date":   to_date(row[10]) if len(row) > 10 else None,
        "follow_up_date":  to_date(row[11]) if len(row) > 11 else None,
        "is_urgent":  (row[12] or None) if len(row) > 12 else None,
        "referral_month": to_int(row[13]) if len(row) > 13 else None,
        "referral_year":  to_int(row[14]) if len(row) > 14 else None,
        "attended":   to_bool(row[16]) if len(row) > 16 else None,
        "not_attended_reason": (row[17] or None) if len(row) > 17 else None,
        "meeting_date": to_date(row[18]) if len(row) > 18 else None,
        "signed":     to_bool(row[20]) if len(row) > 20 else None,
        "case_amount": to_num(row[21]) if len(row) > 21 else None,
        "first_payment_amount": to_num(row[22]) if len(row) > 22 else None,
        "first_payment_date":   to_date(row[23]) if len(row) > 23 else None,
        "installment_count": to_int(row[25]) if len(row) > 25 else None,
        "unpaid_amount":     to_num(row[26]) if len(row) > 26 else None,
        "installment_schedule": schedule or None,
        "is_cross_month": (row[50] or None) if len(row) > 50 else None,
        "payment_month":  to_int(row[53]) if len(row) > 53 else None,
        "payment_year":   to_int(row[54]) if len(row) > 54 else None,
    }


# 分期付款案件表 [4]: 跟總表 schema 同，但 col offset +1
# header row 2: 0=A spacer / 1=B 010窗口 / 2=C 進線管道 / 3=D 地區
#  4=E 當事人 / 5=F 電話 / 6=G 案件類型 / 7=H 案由 / 8=I 備註 / 9=J 接案律師
# 10=K 進線日期 / 11=L 轉線日期 / 12=M 追蹤日期 / 13=N 急案 / 14=O 月 / 15=P 年
# 16=Q (spacer) / 17=R 出席 / 18=S 未出席原因 / 19=T 會議日期 / 20=U 身分證
# 21=V 委任 / 22=W 委任金額 / 23=X 第一次收款金額 / 24=Y 第一次收款日期
# 25=Z 備註 / 26=AA 分期期數 / 27=AB 未付金額
# 28=AC 第二期日 / 29=AD 第二期額 / ... 49=AW/AX 第十二期
INSTALL_COL_PAIRS_4 = [(28, 29), (30, 31), (32, 33), (34, 35), (36, 37), (38, 39),
                       (40, 41), (42, 43), (44, 45), (46, 47), (48, 49)]


def parse_installment_row(row, sheet_row_idx):
    if len(row) < 15: return None
    name = row[4] if len(row) > 4 else ""
    intake_date = to_date(row[10] if len(row) > 10 else None)
    handling_lawyer = row[9] if len(row) > 9 else None
    if not name and not intake_date: return None

    case_key = hash_key(name, intake_date, handling_lawyer, "inst", sheet_row_idx)

    schedule = []
    for di, ai in INSTALL_COL_PAIRS_4:
        d = to_date(row[di]) if di < len(row) else None
        a = to_num(row[ai]) if ai < len(row) else None
        if d or a:
            schedule.append({"date": d, "amount": a})

    return {
        "case_key": case_key,
        "sheet_row": sheet_row_idx,
        "team_owner": (row[1] or None) if len(row) > 1 else None,
        "channel":    (row[2] or None) if len(row) > 2 else None,
        "region":     (row[3] or None) if len(row) > 3 else None,
        "case_type":  (row[6] or None) if len(row) > 6 else None,
        "case_reason":(row[7] or None) if len(row) > 7 else None,
        "handling_lawyer": handling_lawyer or None,
        "intake_date":     intake_date,
        "referral_date":   to_date(row[11]) if len(row) > 11 else None,
        "follow_up_date":  to_date(row[12]) if len(row) > 12 else None,
        "referral_month":  to_int(row[14]) if len(row) > 14 else None,
        "referral_year":   to_int(row[15]) if len(row) > 15 else None,
        "attended":        to_bool(row[17]) if len(row) > 17 else None,
        "signed":          to_bool(row[21]) if len(row) > 21 else None,
        "case_amount":     to_num(row[22]) if len(row) > 22 else None,
        "first_payment_amount": to_num(row[23]) if len(row) > 23 else None,
        "first_payment_date":   to_date(row[24]) if len(row) > 24 else None,
        "installment_count": to_int(row[26]) if len(row) > 26 else None,
        "unpaid_amount":     to_num(row[27]) if len(row) > 27 else None,
        "installment_schedule": schedule or None,
    }


# ============================================================
# Pull all sheets
# ============================================================

def fetch_zonghyu():
    """總表 [10] 全部資料 (~20K rows)，paginated by range."""
    print("Fetching 總表...")
    rows = []
    # row 3 起是 data；max_row 20373 per metadata
    BATCH = 5000
    for start in range(3, 21000, BATCH):
        end = start + BATCH - 1
        rng = f"'總表'!A{start}:BC{end}"
        chunk = get_range(rng, render="UNFORMATTED_VALUE")
        if not chunk: break
        for ri, r in enumerate(chunk):
            parsed = parse_zonghyu_row(r, start + ri)
            if parsed: rows.append(parsed)
        print(f"  {start}-{end}: +{len(chunk)} raw → {len(rows)} parsed total")
        if len(chunk) < BATCH: break
    return rows


def fetch_installment():
    print("Fetching 分期付款案件表...")
    rows = []
    BATCH = 2000
    for start in range(3, 5000, BATCH):
        end = start + BATCH - 1
        rng = f"'分期付款案件表'!A{start}:AX{end}"
        chunk = get_range(rng, render="UNFORMATTED_VALUE")
        if not chunk: break
        for ri, r in enumerate(chunk):
            parsed = parse_installment_row(r, start + ri)
            if parsed: rows.append(parsed)
        print(f"  {start}-{end}: +{len(chunk)} raw → {len(rows)} parsed total")
        if len(chunk) < BATCH: break
    return rows


def fetch_lawyer_target():
    """每週/月轉介律師目標案件數 [9] row 3-62 monthly section."""
    print("Fetching 律師目標表 monthly section...")
    rows = get_range("'每週/月轉介律師目標案件數'!A1:AZ62", render="FORMATTED_VALUE")
    if len(rows) < 3: return []
    # row 2 (idx 1) is header
    hdr = rows[1]
    # 從 col index 4 起是 lawyer columns (col D 是「目標數自動加總」col E="喆律")
    # Actually row 3 sample: ['', '2022', '6', '425', '10', '10', '15', '10', '50', '90', '40', '', '20', '15']
    # col 0 = empty, col 1 = year, col 2 = month, col 3 = 自動加總, col 4+ = individual lawyer
    lawyer_cols = []
    for ci in range(4, len(hdr)):
        name = (hdr[ci] or "").strip()
        if name and not name.startswith(("年", "月", "日")):
            lawyer_cols.append((ci, name))
    print(f"  lawyer cols: {len(lawyer_cols)}")
    out = []
    for r in rows[2:]:
        if len(r) < 4: continue
        year = to_int(r[1] if len(r) > 1 else None)
        month = to_int(r[2] if len(r) > 2 else None)
        if not year or not month: continue
        for ci, name in lawyer_cols:
            v = r[ci] if ci < len(r) else None
            t = to_int(v)
            if t is None and v not in ("依公告", "家事", None, ""):
                continue
            out.append({
                "year": year,
                "month": month,
                "lawyer": name,
                "monthly_target": t,
                "weekly_target": None,  # v1 skip
                "region": None,
            })
    print(f"  total target rows: {len(out)}")
    return out


# ============================================================
# Main
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pull", action="store_true", help="skip sheet fetch, only rebuild + reconcile")
    ap.add_argument("--year-from", type=int, default=2021)
    ap.add_argument("--year-to", type=int, default=2030)
    ap.add_argument("--reconcile-year", type=int, default=2026)
    ap.add_argument("--reconcile-month", type=int, default=5)
    args = ap.parse_args()

    if not args.skip_pull:
        # 1. Pull + upsert 總表
        z = fetch_zonghyu()
        print(f"\nupserting {len(z)} raw_010_case rows...")
        supabase_upsert("raw_010_case", z)

        # 2. Pull + upsert 分期付款
        i = fetch_installment()
        print(f"\nupserting {len(i)} raw_010_installment_case rows...")
        supabase_upsert("raw_010_installment_case", i)

        # 3. Pull + upsert 律師目標
        t = fetch_lawyer_target()
        print(f"\nupserting {len(t)} raw_010_lawyer_target rows...")
        supabase_upsert("raw_010_lawyer_target", t, on_conflict="year,month,lawyer")

    # 4. Rebuild fact tables
    print("\nrebuilding fact_010_monthly_team...")
    r = supabase_rpc("rebuild_fact_010_monthly_team",
                     {"p_year_from": args.year_from, "p_year_to": args.year_to})
    print(f"  affected: {r}")
    print("\nrebuilding fact_010_monthly_lawyer...")
    r = supabase_rpc("rebuild_fact_010_monthly_lawyer",
                     {"p_year_from": args.year_from, "p_year_to": args.year_to})
    print(f"  affected: {r}")

    # 5. Reconciliation: pull 2026-05 fact tables + print
    print(f"\n{'='*80}\nReconciliation: {args.reconcile_year}-{args.reconcile_month:02d}\n{'='*80}")
    teams = supabase_query("fact_010_monthly_team",
                          select="*",
                          year=f"eq.{args.reconcile_year}",
                          month=f"eq.{args.reconcile_month}",
                          order="total_revenue.desc")
    print(f"\n--- 010 同仁 fact_010_monthly_team ({len(teams)} rows) ---")
    print(f"{'member':<6} {'當月業績':>10} {'總業績':>10} {'件數':>4} {'010流量':>6} {'喆律流量':>6} {'出席':>4} {'委任':>4} {'出席率':>7} {'成案率':>7} {'委任均價':>10}")
    for t in teams:
        print(f"{t['team_member']:<6} {t['current_month_revenue']:>10,.0f} {t['total_revenue']:>10,.0f} "
              f"{t['total_referrals']:>4} {t['o10_referrals']:>6} {t['zhelu_referrals']:>6} "
              f"{t['attended']:>4} {t['signed']:>4} "
              f"{(t['attend_rate'] or 0)*100:>6.2f}% {(t['sign_rate'] or 0)*100:>6.2f}% "
              f"{t['avg_signed_amount']:>10,.0f}")

    lawyers = supabase_query("fact_010_monthly_lawyer",
                            select="*",
                            year=f"eq.{args.reconcile_year}",
                            month=f"eq.{args.reconcile_month}",
                            order="total_revenue.desc",
                            limit=30)
    print(f"\n--- 合作律師 fact_010_monthly_lawyer (top 30) ---")
    print(f"{'律師':<8} {'件':>3} {'出席':>4} {'委任':>4} {'出席率':>7} {'委任率':>7} {'總金額':>10} {'均單價':>7} {'狀態':<6}")
    for l in lawyers:
        print(f"{l['lawyer']:<8} {l['referrals']:>3} {l['attended']:>4} {l['signed']:>4} "
              f"{(l['attend_rate'] or 0)*100:>6.2f}% {(l['sign_rate'] or 0)*100:>6.2f}% "
              f"{l['total_revenue']:>10,.0f} {(l['avg_unit_price_wan'] or 0):>6.2f} "
              f"{l['referral_status']:<6}")


if __name__ == "__main__":
    main()
