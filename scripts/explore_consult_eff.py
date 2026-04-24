"""
Wave 1 探索分析：諮詢成案效益
- 唯讀，不動任何資料
- 用 SERVICE KEY 繞 RLS 抓全資料

輸出：
  1. 資料總覽
  2. Case type 效益排行（哪類案件最好/最差）
  3. 律師 × case_type 熱度（誰在哪類強）
  4. 會議品質 heuristic × 成案率相關性
  5. 下跌律師預警（rolling 3-month）
"""
import os, io, sys, re, json
from collections import defaultdict
from datetime import datetime
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def fetch_all(table, select, order=None):
    rows, off, page = [], 0, 1000
    while True:
        params = {"select": select, "limit": str(page), "offset": str(off)}
        if order:
            params["order"] = order
        r = httpx.get(f"{URL}/rest/v1/{table}", params=params, headers=HDR, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        off += page
    return rows


# ---------- 會議品質 heuristic（對齊前端 analyzeMeetingRecord）----------
def analyze_meeting(text):
    """回傳 (avg_score, dict of flags) — 簡化版，只取關鍵判斷"""
    if not text or len(text.strip()) < 50:
        return None
    flags = {
        "law_ref": bool(re.search(r"第\d+條|民法|刑法|民事訴訟法|刑事訴訟法|土地法|勞基法", text)),
        "amount":  bool(re.search(r"\d+萬|費用|賠償金|扶養費", text)),
        "risk":    bool(re.search(r"風險|注意|但書|例外|困難|不利", text)),
        "action":  bool(re.search(r"建議.*?[：:]|方案|策略|步驟|程序", text)),
        "evidence": bool(re.search(r"證據|舉證|金流|截圖|錄音|存證信函", text)),
        "timeline": bool(re.search(r"期限|時效|天內|個月|期間|時程", text)),
        "alt":     bool(re.search(r"或者|另外|其他方式|替代|調解|和解|協商", text)),
        "fee":     bool(re.search(r"律師費|訴訟費|裁判費|委任|報酬", text)),
    }
    length_flag = "full" if len(text) > 3000 else ("short" if len(text) < 500 else "medium")
    flags["length"] = length_flag
    score = sum(1 for k, v in flags.items() if k != "length" and v) / 8 * 100
    return score, flags


def fmt_money(n):
    return f"${int(n):,}"


def main():
    print("=" * 72)
    print("Wave 1 探索分析：諮詢成案效益")
    print("=" * 72)

    # ---------- Fetch ----------
    print("\n[抓資料中...]")
    lawyers = fetch_all("lawyers", "id,name,is_active,role,office")
    lmap = {l["id"]: l for l in lawyers}
    cases = fetch_all(
        "consultation_cases",
        "id,lawyer_id,case_date,case_type,is_signed,revenue,collected,meeting_record,transcript",
        order="case_date.desc",
    )
    stats = fetch_all("monthly_stats", "lawyer_id,month,consult_count,signed_count,revenue,collected")
    print(f"  lawyers={len(lawyers)}  cases={len(cases)}  monthly_stats={len(stats)}")

    # ---------- 1. 資料總覽 ----------
    print("\n" + "=" * 72)
    print("1. 資料總覽")
    print("=" * 72)
    total_consult = sum(s.get("consult_count") or 0 for s in stats)
    total_signed  = sum(s.get("signed_count")  or 0 for s in stats)
    total_collect = sum(s.get("collected")     or 0 for s in stats)
    months = sorted({s["month"] for s in stats})
    print(f"律師人數（有資料的）: {len({s['lawyer_id'] for s in stats})}")
    print(f"月份範圍: {months[0] if months else '—'} ~ {months[-1] if months else '—'} ({len(months)} 個月)")
    print(f"累計諮詢: {total_consult:,}")
    print(f"累計簽約: {total_signed:,}")
    print(f"全所簽約率: {total_signed/total_consult*100:.2f}%" if total_consult else "—")
    print(f"累計已收: {fmt_money(total_collect)}")
    print(f"全所 consult_eff: {fmt_money(total_collect/total_consult)}" if total_consult else "—")
    print(f"consultation_cases 筆數: {len(cases)}")
    print(f"  — 有 meeting_record: {sum(1 for c in cases if c.get('meeting_record'))}")
    print(f"  — 有 transcript:     {sum(1 for c in cases if c.get('transcript'))}")
    print(f"  — 已簽約:            {sum(1 for c in cases if c.get('is_signed'))}")

    # ---------- 2. Case type 效益排行 ----------
    print("\n" + "=" * 72)
    print("2. Case type 效益排行（樣本 >= 5 的類型）")
    print("=" * 72)
    by_type = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0, "revenue": 0})
    for c in cases:
        t = (c.get("case_type") or "").strip() or "(未分類)"
        # 清洗：取主類型（用逗號切）
        t = re.split(r"[,，、]", t)[0].strip()
        t = t.replace("諮詢", "") or t
        by_type[t]["n"] += 1
        if c.get("is_signed"):
            by_type[t]["signed"] += 1
        by_type[t]["collected"] += (c.get("collected") or 0)
        by_type[t]["revenue"]   += (c.get("revenue") or 0)

    rows = []
    for t, d in by_type.items():
        if d["n"] < 5:
            continue
        rate = d["signed"] / d["n"] * 100
        avg  = d["collected"] / d["signed"] if d["signed"] else 0
        eff  = d["collected"] / d["n"]
        rows.append((t, d["n"], d["signed"], rate, avg, eff))

    rows.sort(key=lambda r: -r[5])
    print(f"{'類型':<16}{'諮詢':>6}{'簽約':>6}{'簽率':>8}{'平均收款':>14}{'consult_eff':>14}")
    for r in rows[:25]:
        print(f"{r[0][:16]:<16}{r[1]:>6}{r[2]:>6}{r[3]:>7.1f}%{fmt_money(r[4]):>14}{fmt_money(r[5]):>14}")
    if len(rows) > 25:
        print(f"... (共 {len(rows)} 類，只顯示前 25)")

    # 最差類型（倒著看）
    print("\n  — 效益最差 5 類 —")
    for r in sorted(rows, key=lambda x: x[5])[:5]:
        print(f"{r[0][:16]:<16}{r[1]:>6}{r[2]:>6}{r[3]:>7.1f}%{fmt_money(r[4]):>14}{fmt_money(r[5]):>14}")

    # ---------- 3. 律師 × case_type（找出錯配）----------
    print("\n" + "=" * 72)
    print("3. 律師 × case_type 錯配分析")
    print("    「律師在某類型的簽約率 vs 該類型全所平均」")
    print("=" * 72)
    # 每律師每類型的 n, signed
    lt = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in cases:
        lid = c["lawyer_id"]
        t = (c.get("case_type") or "").strip() or "(未分類)"
        t = re.split(r"[,，、]", t)[0].strip().replace("諮詢", "") or t
        lt[(lid, t)]["n"] += 1
        if c.get("is_signed"):
            lt[(lid, t)]["signed"] += 1
        lt[(lid, t)]["collected"] += (c.get("collected") or 0)

    # type baseline
    type_rate = {r[0]: r[3] for r in rows}
    gap_rows = []
    for (lid, t), d in lt.items():
        if d["n"] < 5 or t not in type_rate:
            continue
        rate = d["signed"] / d["n"] * 100
        gap = rate - type_rate[t]
        gap_rows.append((lmap.get(lid, {}).get("name", "?"), t, d["n"], rate, type_rate[t], gap))

    print("\n  Top 10 正向錯配（該律師 × 該類型遠高於平均 → 這類案件該多給這人）：")
    gap_rows.sort(key=lambda r: -r[5])
    print(f"{'律師':<8}{'類型':<16}{'n':>4}{'本人':>8}{'基準':>8}{'差距':>8}")
    for r in gap_rows[:10]:
        print(f"{r[0][:8]:<8}{r[1][:16]:<16}{r[2]:>4}{r[3]:>7.1f}%{r[4]:>7.1f}%{r[5]:>+7.1f}%")

    print("\n  Top 10 負向錯配（遠低於平均 → 考慮改派或培訓）：")
    gap_rows.sort(key=lambda r: r[5])
    print(f"{'律師':<8}{'類型':<16}{'n':>4}{'本人':>8}{'基準':>8}{'差距':>8}")
    for r in gap_rows[:10]:
        print(f"{r[0][:8]:<8}{r[1][:16]:<16}{r[2]:>4}{r[3]:>7.1f}%{r[4]:>7.1f}%{r[5]:>+7.1f}%")

    # ---------- 4. 會議品質 heuristic × 成案率 ----------
    print("\n" + "=" * 72)
    print("4. 會議品質 8 維度 × 是否簽約")
    print("    （只看有 meeting_record 且長度 >= 50 的案件）")
    print("=" * 72)
    mr_cases = [c for c in cases if c.get("meeting_record")]
    signed_mr   = [c for c in mr_cases if c.get("is_signed")]
    unsigned_mr = [c for c in mr_cases if not c.get("is_signed")]
    print(f"有會議記錄: {len(mr_cases)}（簽約 {len(signed_mr)} / 未簽 {len(unsigned_mr)}）")
    if not mr_cases:
        print("  [沒有會議記錄資料，跳過]")
    else:
        dims = ["law_ref", "amount", "risk", "action", "evidence", "timeline", "alt", "fee"]
        dim_zh = {"law_ref":"法條引用", "amount":"金額分析", "risk":"風險提示",
                  "action":"行動方案", "evidence":"證據指引", "timeline":"時程規劃",
                  "alt":"替代方案", "fee":"費用說明"}

        def rate_of(cases_list, d):
            n = 0; pos = 0
            for c in cases_list:
                r = analyze_meeting(c.get("meeting_record"))
                if r is None: continue
                n += 1
                if r[1][d]: pos += 1
            return pos/n*100 if n else 0

        print(f"\n{'維度':<12}{'簽約有此項%':>14}{'未簽有此項%':>14}{'差距':>10}")
        diffs = []
        for d in dims:
            s = rate_of(signed_mr, d)
            u = rate_of(unsigned_mr, d)
            diffs.append((dim_zh[d], s, u, s-u))
        diffs.sort(key=lambda r: -abs(r[3]))
        for n, s, u, gap in diffs:
            arrow = "↑" if gap > 0 else ("↓" if gap < 0 else " ")
            print(f"{n:<12}{s:>13.1f}%{u:>13.1f}%{gap:>+8.1f}% {arrow}")

        # 平均分數對比
        def avg_score(cases_list):
            scores = []
            for c in cases_list:
                r = analyze_meeting(c.get("meeting_record"))
                if r: scores.append(r[0])
            return sum(scores)/len(scores) if scores else 0
        print(f"\n平均會議品質分數：簽約 {avg_score(signed_mr):.1f} / 未簽 {avg_score(unsigned_mr):.1f}")

    # ---------- 5. 下跌律師預警 ----------
    print("\n" + "=" * 72)
    print("5. 下跌律師預警（最近 3 月 vs 前 3 月）")
    print("=" * 72)
    if not months:
        print("  [沒有 monthly_stats]")
    else:
        recent3 = months[-3:]
        prev3   = months[-6:-3]
        if len(recent3) < 3 or len(prev3) < 3:
            print(f"  資料不足 6 個月（目前 {len(months)} 月），用全部可用月份比對")
        print(f"  最近 3 月: {recent3}")
        print(f"  前 3 月:   {prev3}")

        by_law = defaultdict(lambda: {"r_c":0,"r_s":0,"r_col":0,"p_c":0,"p_s":0,"p_col":0})
        for s in stats:
            lid = s["lawyer_id"]; m = s["month"]
            c = s.get("consult_count") or 0; sg = s.get("signed_count") or 0; co = s.get("collected") or 0
            if m in recent3:
                by_law[lid]["r_c"] += c; by_law[lid]["r_s"] += sg; by_law[lid]["r_col"] += co
            elif m in prev3:
                by_law[lid]["p_c"] += c; by_law[lid]["p_s"] += sg; by_law[lid]["p_col"] += co

        alerts = []
        for lid, d in by_law.items():
            if d["p_c"] < 3 or d["r_c"] < 3:
                continue
            r_rate = d["r_s"]/d["r_c"]*100
            p_rate = d["p_s"]/d["p_c"]*100
            r_eff  = d["r_col"]/d["r_c"]
            p_eff  = d["p_col"]/d["p_c"]
            alerts.append({
                "name": lmap.get(lid, {}).get("name", "?"),
                "r_c": d["r_c"], "p_c": d["p_c"],
                "r_rate": r_rate, "p_rate": p_rate, "d_rate": r_rate - p_rate,
                "r_eff": r_eff, "p_eff": p_eff, "d_eff": r_eff - p_eff,
            })

        print(f"\n  簽約率下跌最多前 10（需要 n>=3）：")
        alerts_r = sorted(alerts, key=lambda a: a["d_rate"])[:10]
        print(f"{'律師':<8}{'前n':>5}{'近n':>5}{'前率':>8}{'近率':>8}{'Δ率':>8}{'Δ eff':>14}")
        for a in alerts_r:
            print(f"{a['name'][:8]:<8}{a['p_c']:>5}{a['r_c']:>5}{a['p_rate']:>7.1f}%{a['r_rate']:>7.1f}%{a['d_rate']:>+7.1f}%{fmt_money(a['d_eff']):>14}")

        print(f"\n  consult_eff 下跌最多前 10：")
        alerts_e = sorted(alerts, key=lambda a: a["d_eff"])[:10]
        print(f"{'律師':<8}{'前n':>5}{'近n':>5}{'前eff':>12}{'近eff':>12}{'Δ eff':>14}")
        for a in alerts_e:
            sign = "+" if a['d_eff'] > 0 else ""
            print(f"{a['name'][:8]:<8}{a['p_c']:>5}{a['r_c']:>5}{fmt_money(a['p_eff']):>12}{fmt_money(a['r_eff']):>12}{(sign+fmt_money(a['d_eff'])):>14}")

    print("\n" + "=" * 72)
    print("完成。")
    print("=" * 72)


if __name__ == "__main__":
    main()
