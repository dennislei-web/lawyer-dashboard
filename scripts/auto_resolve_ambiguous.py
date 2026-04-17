"""
自動判斷剩下的 UP_ 假案件該合併到哪個 CRM 真案件。

策略：
  對每個 UP_ 案件 → 撈同日律師的候選真案件 → 對每個候選算配對分數：
    +10  每次 client_name 完整字串出現在 meeting_record/transcript
    + 5  每次姓氏（client_name 第 1 字）連接任何其他 client_name 字元出現
    + 3  case_type 精確相等
    + 2  is_signed 相同
    + 2  case_type 裡特殊關鍵字（如「一審」「二審」）在文字裡出現次數

  決策：
    - 分數最高者 > 第二高至少 5 分，且最高分 ≥ 10  → 自動合併
    - 否則 → 標為 LOW_CONFIDENCE，保留不動

預設 dry-run，加 --apply 才實際執行。
"""
import argparse, re, httpx, os, io, sys
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
patch_headers = dict(headers)
patch_headers["Prefer"] = "return=minimal"


def fetch_lawyers():
    r = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name"}, headers=headers, timeout=30)
    r.raise_for_status()
    return {l["id"]: l["name"] for l in r.json()}


def fetch_up_cases():
    r = httpx.get(
        f"{url}/rest/v1/consultation_cases",
        params={
            "select": "id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
            "case_number": "like.UP_*",
            "order": "lawyer_id.asc,case_date.asc",
        },
        headers=headers, timeout=60,
    )
    r.raise_for_status()
    return r.json()


def fetch_same_day_reals(lawyer_id, case_date):
    r = httpx.get(
        f"{url}/rest/v1/consultation_cases",
        params={
            "select": "id,case_number,case_type,client_name,is_signed,revenue,collected,meeting_record,transcript",
            "lawyer_id": f"eq.{lawyer_id}",
            "case_date": f"eq.{case_date}",
        },
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    return [x for x in r.json() if not (x.get("case_number") or "").startswith("UP_")]


COMPANY_KEYWORDS = ["公司", "股份", "有限", "集團", "企業", "商行", "工業", "科技", "國際", "事務所", "協會", "基金會"]


def is_company_name(cn):
    return any(k in cn for k in COMPANY_KEYWORDS)


def score(up, real):
    """為 (up, real) 算匹配分數 — 只用強訊號，避免雜訊"""
    text = ((up.get("meeting_record") or "") + "\n" + (up.get("transcript") or ""))
    sample = text[:3000]
    s = 0
    reasons = []

    cn = (real.get("client_name") or "").strip()
    if cn and len(cn) >= 2:
        # 完整名字出現 — 強訊號
        full_hits = sample.count(cn)
        if full_hits > 0:
            pts = min(10 + 3 * (full_hits - 1), 20)
            s += pts
            reasons.append(f"當事人「{cn}」出現 {full_hits} 次(+{pts})")
        elif not is_company_name(cn) and len(cn) >= 2 and len(cn) <= 4:
            # 只對 2-4 字的人名做「姓+名字末字」的嚴格部分匹配（不是任意字）
            surname = cn[0]
            last_name = cn[-1]
            if surname != last_name:
                # 姓 + 至多 1 個字 + 名末字（符合 3 字姓名結構）
                pattern = re.compile(re.escape(surname) + r".{1,2}" + re.escape(last_name))
                hits = len(pattern.findall(sample))
                if hits > 0:
                    pts = min(8, 4 * hits)  # 封頂 8
                    s += pts
                    reasons.append(f"姓氏+名末字「{surname}…{last_name}」{hits} 次(+{pts})")

    # case_type 完全相等
    ct_up = (up.get("case_type") or "").strip()
    ct_real = (real.get("case_type") or "").strip()
    if ct_up and ct_real and ct_up == ct_real:
        s += 3
        reasons.append("case_type 相等(+3)")
    elif ct_up and ct_real:
        # 部分重疊（UP_ case_type 的任一詞在 real case_type 裡）
        # 先過濾掉「現場諮詢」「視訊諮詢」等通用詞
        GENERIC = {"現場諮詢", "視訊諮詢", "電話諮詢", "諮詢"}
        up_tokens = [t.strip() for t in re.split(r"[,\s、+]+", ct_up) if t.strip() and t.strip() not in GENERIC]
        real_tokens = [t.strip() for t in re.split(r"[,\s、+]+", ct_real) if t.strip() and t.strip() not in GENERIC]
        overlap = set(up_tokens) & set(real_tokens)
        if overlap:
            s += 4
            reasons.append(f"case_type 共通詞「{'/'.join(overlap)}」(+4)")

    # is_signed 相同
    if up.get("is_signed") == real.get("is_signed"):
        s += 2
        reasons.append("is_signed 相同(+2)")

    return s, reasons


def patch_case(case_id, patch):
    r = httpx.patch(
        f"{url}/rest/v1/consultation_cases",
        params={"id": f"eq.{case_id}"},
        json=patch, headers=patch_headers, timeout=30,
    )
    return r.status_code in (200, 204), r.text[:200] if r.status_code not in (200, 204) else ""


def delete_case(case_id):
    r = httpx.delete(
        f"{url}/rest/v1/consultation_cases",
        params={"id": f"eq.{case_id}"},
        headers=patch_headers, timeout=30,
    )
    return r.status_code in (200, 204), r.text[:200] if r.status_code not in (200, 204) else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="實際執行（預設 dry-run）")
    ap.add_argument("--min-score", type=int, default=10, help="最高分至少多少才算匹配（預設 10）")
    ap.add_argument("--min-margin", type=int, default=5, help="最高分比第二高至少多多少（預設 5）")
    args = ap.parse_args()

    print("=" * 70)
    print(f"  UP_ 假案件自動判斷 ({'APPLY' if args.apply else 'DRY-RUN'})")
    print(f"  門檻：最高分 ≥ {args.min_score}，領先差 ≥ {args.min_margin}")
    print("=" * 70)

    lname = fetch_lawyers()
    ups = fetch_up_cases()
    print(f"\n待處理 {len(ups)} 筆 UP_ 案件\n")

    if not ups:
        print("✓ 沒有要處理的案件。")
        return

    decisions = []  # [(up, best_real, scored, decision)]
    for up in ups:
        reals = fetch_same_day_reals(up["lawyer_id"], up["case_date"])
        scored = []
        for r in reals:
            s, reasons = score(up, r)
            scored.append((s, reasons, r))
        scored.sort(key=lambda x: -x[0])

        if not scored:
            decisions.append((up, None, scored, "no_candidates"))
            continue

        best_score, best_reasons, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        margin = best_score - second

        if best_score >= args.min_score and margin >= args.min_margin:
            decisions.append((up, best, scored, "auto"))
        else:
            decisions.append((up, None, scored, "low_confidence"))

    # 列印決策
    auto = [d for d in decisions if d[3] == "auto"]
    low = [d for d in decisions if d[3] == "low_confidence"]
    none = [d for d in decisions if d[3] == "no_candidates"]

    print(f"✓ 自動判斷成功：{len(auto)} 筆")
    print(f"⚠ 信心不足（保留）：{len(low)} 筆")
    print(f"✗ 無候選（CRM 查無）：{len(none)} 筆\n")

    print("─" * 70)
    print("  自動判斷結果：")
    print("─" * 70)
    for up, best, scored, dec in decisions:
        nm = lname.get(up["lawyer_id"], "?")
        label = {"auto": "✓", "low_confidence": "⚠", "no_candidates": "✗"}[dec]
        print(f"\n{label} {nm} {up['case_date']} {up.get('case_type','')}  ({'成案' if up.get('is_signed') else '未成案'})")
        if dec == "no_candidates":
            print("    (CRM 查無同日案件)")
            continue
        for i, (s, reasons, r) in enumerate(scored, 1):
            marker = "→" if (dec == "auto" and r["id"] == best["id"]) else " "
            print(f"    {marker} [{s:>3}] {r['case_number']}  {'成案' if r.get('is_signed') else '未成案':<4}  "
                  f"{(r.get('case_type') or '')[:18]:<18}  {(r.get('client_name') or '')[:10]:<10}")
            if reasons and (dec == "auto" or i <= 2):
                print(f"        理由：{'; '.join(reasons)}")

    if not args.apply:
        print("\n" + "=" * 70)
        print(f"  DRY-RUN。加 --apply 會把 {len(auto)} 筆合併並刪除 UP_ 假案件。")
        print(f"  {len(low)} 筆信心不足的會保留，之後可用 manual_resolve_ambiguous.py 人工處理。")
        print("=" * 70)
        return

    # 實際執行
    print("\n" + "=" * 70)
    print(f"  開始執行 {len(auto)} 筆合併…")
    print("=" * 70)

    moved = 0
    errors = 0
    for up, best, scored, dec in auto:
        patch = {}
        mr = up.get("meeting_record")
        ts = up.get("transcript")
        if mr and not best.get("meeting_record"):
            patch["meeting_record"] = mr
        elif mr and best.get("meeting_record"):
            # 真案件已有內容，保留原樣（合併時不覆蓋）
            pass
        if ts and not best.get("transcript"):
            patch["transcript"] = ts

        if patch:
            ok, err = patch_case(best["id"], patch)
            if not ok:
                print(f"  ✗ patch {best['case_number']} 失敗：{err}")
                errors += 1
                continue

        ok, err = delete_case(up["id"])
        if ok:
            moved += 1
        else:
            print(f"  ✗ delete {up['case_number']} 失敗：{err}")
            errors += 1

    print(f"\n  ✓ 搬移+刪除：{moved} 筆（錯誤 {errors} 筆）")
    print(f"  ⚠ 保留：{len(low) + len(none)} 筆（信心不足或無候選）")


if __name__ == "__main__":
    main()
