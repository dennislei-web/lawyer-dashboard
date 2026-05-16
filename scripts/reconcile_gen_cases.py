"""
GEN_<uuid> 案件對帳：

2026-03-17 一批從會議記錄/逐字稿匯入的案件，case_number 被填成 GEN_<id>，
client_name / 應收 / 已收都是空的。本腳本：

1. 從 meeting_record / transcript 抽出當事人姓名與會議日期關鍵字
2. 對 CRM 匯出的 xlsx 用 (lawyer, case_date, client_name) 比對
3. 找到唯一 match → 計畫 PATCH (case_number, client_name, revenue, collected)
4. 預設 dry-run；加 --apply 才實際寫入

Usage:
  python reconcile_gen_cases.py              # dry-run
  python reconcile_gen_cases.py --apply      # 實際 patch
"""
import os, re, sys, io, argparse
from collections import defaultdict
import httpx
import pandas as pd
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
XLSX = os.path.join(SCRIPT_DIR, "consultation_all_data.xlsx")


# ── 客戶姓名抽取（多策略 fallback）─────────────────────────────────────
_FNAME_RE = re.compile(r"\d{6,7}[\-_ ]+([一-鿿&、\s]{1,16}?)[\-_ ]+(?:會議|現場|諮詢|錄音|逐字)")
# 必須有 ：/:/為 之一，避免抓到「當事人主要訴求」「當事人背景」等段落標題
_PARTY_RE = re.compile(r"當\s*事\s*人(?:為|[:：])\s*([一-鿿&、\s]{2,12})")

# 非姓名片段（出現這些就丟掉）
_BAD_NAME_FRAGMENTS = {"背景", "摘要", "案件", "主要", "訴求", "為", "對啊", "說明", "概要"}

def _clean_name(name: str) -> str | None:
    """正規化抽出來的字串，過濾雜訊"""
    name = name.strip()
    # 去掉前綴「為」（「當事人為XXX」型）
    name = re.sub(r"^為\s*", "", name)
    # 多人案件：& / 、, 後面是對造，只留第一位
    name = re.split(r"[&、,，\s]", name)[0].strip()
    if not (2 <= len(name) <= 6):
        return None
    if name in _BAD_NAME_FRAGMENTS:
        return None
    return name


def extract_client_name(meeting_record: str, transcript: str) -> str | None:
    """從 mr / tx 抽出當事人姓名 — 優先檔名 header，其次內文「當事人：XXX」"""
    # 策略 A：檔名 header（最可靠）
    for src in (meeting_record or "", transcript or ""):
        m = _FNAME_RE.search(src)
        if m:
            n = _clean_name(m.group(1))
            if n: return n
    # 策略 B：內文「當事人：XXX」或「當事人為XXX」
    for src in (meeting_record or "", transcript or ""):
        m = _PARTY_RE.search(src)
        if m:
            n = _clean_name(m.group(1))
            if n: return n
    return None


# ── 取 GEN_ rows ──
def fetch_gen_rows():
    r = httpx.get(f"{URL}/rest/v1/consultation_cases",
        params={"select":"id,case_number,case_date,case_type,is_signed,lawyer_id,meeting_record,transcript",
                "case_number":"like.GEN_*",
                "order":"case_date.asc"},
        headers=HDR, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_lawyer_map():
    r = httpx.get(f"{URL}/rest/v1/lawyers",
        params={"select":"id,name"}, headers=HDR, timeout=30)
    r.raise_for_status()
    return {l["id"]: l["name"] for l in r.json()}


# ── 主要對帳 ────────────────────────────────────────────────────────
def load_xlsx_index():
    """xlsx 索引：{(lawyer_name, date_str): [row_dict]}"""
    df = pd.read_excel(XLSX)
    df.columns = df.columns.str.strip()
    df["諮詢日期"] = pd.to_datetime(df["諮詢日期"], errors="coerce")
    df = df.dropna(subset=["諮詢日期"])
    df["date_str"] = df["諮詢日期"].dt.strftime("%Y-%m-%d")

    rev_col = next((c for c in df.columns if "應收" in c), None)
    col_col = next((c for c in df.columns if "已收" in c), None)
    for c in (rev_col, col_col):
        if c:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", "").str.strip(),
                errors="coerce"
            ).fillna(0).astype(int)

    idx = defaultdict(list)
    for _, r in df.iterrows():
        # 多律師案件：每位律師都索引到（避免 "林昀, 吳柏慶" 拆鍵後第一位匹配不到）
        raw = str(r.get("諮詢律師", ""))
        for lname in [x.strip() for x in re.split(r"[,、]", raw) if x.strip()]:
            key = (lname, r["date_str"])
            idx[key].append({
                "案件編號": str(r.get("案件編號","")).strip(),
                "當事人":   str(r.get("當事人","")).strip(),
                "服務項目": str(r.get("服務項目","")).strip(),
                "簽約狀態": str(r.get("簽約狀態","")).strip(),
                "revenue":  int(r.get(rev_col, 0)) if rev_col else 0,
                "collected":int(r.get(col_col, 0)) if col_col else 0,
            })
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="實際 patch（預設 dry-run）")
    args = ap.parse_args()

    print(f"=== GEN_ 案件對帳 ({'APPLY' if args.apply else 'DRY-RUN'}) ===\n")

    lmap = fetch_lawyer_map()
    rows = fetch_gen_rows()
    print(f"GEN_ 案件：{len(rows)} 筆")

    xlsx_idx = load_xlsx_index()
    print(f"xlsx 索引：{len(xlsx_idx)} 個 (lawyer, date) 鍵\n")

    stats = defaultdict(int)
    patches = []
    unmatched = []

    for r in rows:
        nm = lmap.get(r["lawyer_id"], "?")
        client = extract_client_name(r.get("meeting_record"), r.get("transcript"))
        if not client:
            stats["no_client_name"] += 1
            unmatched.append((r, nm, None, "無法抽出當事人姓名"))
            continue

        candidates = xlsx_idx.get((nm, r["case_date"]), [])
        if not candidates:
            stats["xlsx_no_date"] += 1
            unmatched.append((r, nm, client, f"xlsx 無 ({nm}, {r['case_date']}) 該日期"))
            continue

        # 找當事人姓名 substring 匹配的
        matches = [c for c in candidates if client in c["當事人"] or c["當事人"] in client]
        if len(matches) == 0:
            stats["xlsx_name_mismatch"] += 1
            avail = ", ".join(f"{c['當事人']}" for c in candidates[:5])
            unmatched.append((r, nm, client, f"當天 xlsx {nm} 有 {len(candidates)} 筆但都不含「{client}」: [{avail}]"))
            continue
        if len(matches) > 1:
            # 同人同日多案 → 用 case_type 二次篩
            matches2 = [c for c in matches if r["case_type"] and r["case_type"] in c["服務項目"]] or matches
            if len(matches2) > 1:
                stats["xlsx_ambiguous"] += 1
                avail = ", ".join(f"{c['當事人']}/{c['服務項目']}/{c['案件編號']}" for c in matches2[:5])
                unmatched.append((r, nm, client, f"多筆 candidate 無法定唯一: [{avail}]"))
                continue
            matches = matches2

        m = matches[0]
        patches.append({
            "id": r["id"],
            "old_case_number": r["case_number"],
            "new": {
                "case_number": m["案件編號"] or r["case_number"],
                "client_name": m["當事人"],
                "revenue":   m["revenue"],
                "collected": m["collected"],
            },
            "_dbg": {"lawyer": nm, "date": r["case_date"], "extracted": client}
        })
        stats["matched"] += 1

    print(f"統計：{dict(stats)}\n")

    if patches:
        print(f"=== 將要更新 {len(patches)} 筆 ===")
        print(f"{'date':<11} {'lawyer':<8} {'extracted':<6}  →  {'新 case_number':<14} {'當事人':<10} ${'revenue':>8} ${'collected':>8}")
        for p in patches[:30]:
            n = p["new"]
            d = p["_dbg"]
            print(f"{d['date']:<11} {d['lawyer']:<8} {d['extracted']:<6}  →  {n['case_number']:<14} {n['client_name']:<10} ${n['revenue']:>8,} ${n['collected']:>8,}")
        if len(patches) > 30:
            print(f"... (還有 {len(patches)-30} 筆省略)")

    if unmatched:
        print(f"\n=== 對不到 {len(unmatched)} 筆 ===")
        for r, nm, client, reason in unmatched[:30]:
            print(f"  {r['case_date']} {nm:<8} extracted={client or '(無)':<8} | {reason}")
        if len(unmatched) > 30:
            print(f"  ... (還有 {len(unmatched)-30} 筆省略)")

    if not args.apply:
        print(f"\n[DRY-RUN] 沒實際寫入。確認沒問題後加 --apply 跑一次")
        return

    # ── APPLY：merge GEN → REAL，然後刪除 GEN ──
    # 注意：GEN row 跟 case_number 相同的 REAL row 已存在（daily_update 寫的），
    # 所以不能直接把 GEN.case_number 改成真 case_number（會撞 unique constraint）。
    # 正確做法：把 GEN 的 mr/tx 搬到 REAL，re-point case_chunks，刪掉 GEN
    print(f"\n=== APPLY：merge GEN_ → 真實 row 並刪除 GEN_ ===")
    patch_hdr = {**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"}
    rep_hdr   = {**HDR, "Content-Type": "application/json", "Prefer": "return=representation"}

    ok, fail = 0, 0
    for p in patches:
        gen_id = p["id"]
        target_case_number = p["new"]["case_number"]
        d = p["_dbg"]

        # 1) 找 REAL row id
        rr = httpx.get(f"{URL}/rest/v1/consultation_cases",
            params={"select":"id,meeting_record,transcript", "case_number": f"eq.{target_case_number}"},
            headers=HDR, timeout=30)
        if rr.status_code != 200 or not rr.json():
            fail += 1
            print(f"  ✗ {d['date']} {d['lawyer']} {p['new']['client_name']}: 找不到 case_number={target_case_number} 的真實 row")
            continue
        real = rr.json()[0]
        real_id = real["id"]

        # 2) 取 GEN row 的 mr/tx
        gg = httpx.get(f"{URL}/rest/v1/consultation_cases",
            params={"select":"meeting_record,transcript", "id": f"eq.{gen_id}"},
            headers=HDR, timeout=30).json()[0]

        # 3) 如果 REAL 已經有內容就保留 REAL 的；否則用 GEN 的補
        new_mr = real.get("meeting_record") or gg.get("meeting_record")
        new_tx = real.get("transcript")     or gg.get("transcript")
        if new_mr != real.get("meeting_record") or new_tx != real.get("transcript"):
            r = httpx.patch(f"{URL}/rest/v1/consultation_cases",
                params={"id": f"eq.{real_id}"},
                json={"meeting_record": new_mr, "transcript": new_tx},
                headers=patch_hdr, timeout=30)
            if r.status_code not in (200, 204):
                fail += 1
                print(f"  ✗ {d['date']} {d['lawyer']} {p['new']['client_name']}: REAL PATCH 失敗 {r.status_code} {r.text[:150]}")
                continue

        # 4) Re-point case_chunks（避免 CASCADE 刪掉 embeddings）
        r2 = httpx.patch(f"{URL}/rest/v1/case_chunks",
            params={"case_id": f"eq.{gen_id}"},
            json={"case_id": real_id},
            headers=patch_hdr, timeout=30)
        if r2.status_code not in (200, 204):
            fail += 1
            print(f"  ✗ {d['date']} {d['lawyer']} {p['new']['client_name']}: case_chunks repoint 失敗 {r2.status_code} {r2.text[:200]}")
            continue

        # 5) 刪掉 GEN row
        r3 = httpx.delete(f"{URL}/rest/v1/consultation_cases",
            params={"id": f"eq.{gen_id}"},
            headers=patch_hdr, timeout=30)
        if r3.status_code not in (200, 204):
            fail += 1
            print(f"  ✗ {d['date']} {d['lawyer']} {p['new']['client_name']}: DELETE GEN 失敗 {r3.status_code} {r3.text[:200]}")
            continue

        ok += 1
        if ok <= 5 or ok % 10 == 0:
            print(f"  ✓ [{ok}/{len(patches)}] {d['date']} {d['lawyer']:<6} {p['new']['client_name']:<10} {target_case_number}")

    print(f"\n成功 {ok} 筆，失敗 {fail} 筆")


if __name__ == "__main__":
    main()
