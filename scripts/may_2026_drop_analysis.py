"""
五月 2026 諮詢成案率下滑歸因分析（唯讀）

目標：
1. 確認 5 月（截至 5/19）相對前幾個月的下滑幅度
2. 找出主要拖累的律師
3. 找出主要拖累的案型
4. 用「同期比較」校正（5/1–5/19 vs 各前月 1–19 日）以避免月份未完整的偏誤
"""
import os, io, sys
from collections import defaultdict
from datetime import date
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv("/Users/dennislei/projects/lawyer-dashboard/scripts/.env")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

TODAY = date(2026, 5, 19)
CUTOFF_DAY = TODAY.day  # 19

def fetch_all(table, select, order=None, extra_params=None):
    rows, off, page = [], 0, 1000
    while True:
        params = {"select": select, "limit": str(page), "offset": str(off)}
        if order: params["order"] = order
        if extra_params: params.update(extra_params)
        r = httpx.get(f"{URL}/rest/v1/{table}", params=params, headers=HDR, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page: break
        off += page
    return rows


def parse_date(s):
    return date.fromisoformat(s) if s else None


def main():
    print("=" * 76)
    print(f"五月 2026 諮詢下滑分析（截至 {TODAY}）")
    print("=" * 76)

    # 抓近 7 個月（2025-11 ~ 2026-05）案件
    print("\n[抓資料...]")
    lawyers = fetch_all("lawyers", "id,name,is_active,role")
    lmap = {l["id"]: l["name"] for l in lawyers}

    cases = fetch_all(
        "consultation_cases",
        "id,lawyer_id,case_date,case_type,is_signed,revenue,collected",
        extra_params={"case_date": "gte.2025-11-01"},
        order="case_date.asc",
    )
    print(f"  cases={len(cases)} ({lawyers[0].get('name', '?')} 等 {len(lawyers)} 律師)")

    # ========== 1. 月度全所趨勢（完整月）+ 五月部分 ==========
    print("\n" + "=" * 76)
    print("1. 月度全所趨勢")
    print("=" * 76)
    by_month = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in cases:
        d = parse_date(c["case_date"])
        if not d: continue
        m = d.strftime("%Y-%m")
        by_month[m]["n"] += 1
        if c["is_signed"]: by_month[m]["signed"] += 1
        by_month[m]["collected"] += (c["collected"] or 0)

    print(f"{'月份':<10}{'諮詢':>6}{'簽約':>6}{'簽率':>8}{'已收':>14}{'每諮詢產值':>14}")
    for m in sorted(by_month):
        d = by_month[m]
        rate = d["signed"] / d["n"] * 100 if d["n"] else 0
        eff = d["collected"] / d["n"] if d["n"] else 0
        marker = "  ← 截至 5/19" if m == "2026-05" else ""
        print(f"{m:<10}{d['n']:>6}{d['signed']:>6}{rate:>7.1f}%{int(d['collected']):>14,}{int(eff):>14,}{marker}")

    # ========== 2. 同期比較：每月 1-19 日 ==========
    print("\n" + "=" * 76)
    print(f"2. 同期校正：各月 1–{CUTOFF_DAY} 日（去除月份長度影響）")
    print("=" * 76)
    by_month_sameperiod = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in cases:
        d = parse_date(c["case_date"])
        if not d or d.day > CUTOFF_DAY: continue
        m = d.strftime("%Y-%m")
        by_month_sameperiod[m]["n"] += 1
        if c["is_signed"]: by_month_sameperiod[m]["signed"] += 1
        by_month_sameperiod[m]["collected"] += (c["collected"] or 0)

    print(f"{'月份':<10}{'諮詢(1-19)':>12}{'簽約':>6}{'簽率':>8}{'已收':>14}")
    for m in sorted(by_month_sameperiod):
        d = by_month_sameperiod[m]
        rate = d["signed"] / d["n"] * 100 if d["n"] else 0
        print(f"{m:<10}{d['n']:>12}{d['signed']:>6}{rate:>7.1f}%{int(d['collected']):>14,}")

    # ========== 3. 律師層級：5 月 vs 前 3 月平均（同期 1-19）==========
    print("\n" + "=" * 76)
    print(f"3. 律師下滑排行：5/1–5/{CUTOFF_DAY} vs 2/1–4/{CUTOFF_DAY}（前 3 月同期平均）")
    print("=" * 76)

    # 律師 × 月 同期統計
    lm = defaultdict(lambda: defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0}))
    for c in cases:
        d = parse_date(c["case_date"])
        if not d or d.day > CUTOFF_DAY: continue
        m = d.strftime("%Y-%m")
        lid = c["lawyer_id"]
        lm[lid][m]["n"] += 1
        if c["is_signed"]: lm[lid][m]["signed"] += 1
        lm[lid][m]["collected"] += (c["collected"] or 0)

    prior_months = ["2026-02", "2026-03", "2026-04"]
    rows = []
    for lid, months in lm.items():
        may = months.get("2026-05", {"n": 0, "signed": 0, "collected": 0})
        prior_n = sum(months.get(m, {}).get("n", 0) for m in prior_months)
        prior_signed = sum(months.get(m, {}).get("signed", 0) for m in prior_months)
        prior_coll = sum(months.get(m, {}).get("collected", 0) for m in prior_months)
        prior_avg_n = prior_n / 3
        prior_rate = prior_signed / prior_n * 100 if prior_n else 0
        may_rate = may["signed"] / may["n"] * 100 if may["n"] else 0
        rate_gap = may_rate - prior_rate
        vol_gap = may["n"] - prior_avg_n
        coll_gap = may["collected"] - prior_coll / 3
        # 過濾低樣本
        if prior_n < 5 and may["n"] < 3: continue
        rows.append({
            "name": lmap.get(lid, "?"),
            "may_n": may["n"], "may_signed": may["signed"], "may_rate": may_rate,
            "prior_avg_n": prior_avg_n, "prior_rate": prior_rate,
            "rate_gap": rate_gap, "vol_gap": vol_gap,
            "may_coll": may["collected"], "prior_avg_coll": prior_coll / 3, "coll_gap": coll_gap,
        })

    print("\n  ── 簽約率掉最多 Top 10 ──")
    print(f"{'律師':<10}{'5月諮詢':>8}{'5月簽率':>9}{'前3月簽率':>12}{'簽率差':>9}{'收款落差':>12}")
    for r in sorted(rows, key=lambda x: x["rate_gap"])[:10]:
        print(f"{r['name'][:10]:<10}{r['may_n']:>8}{r['may_rate']:>8.1f}%{r['prior_rate']:>11.1f}%{r['rate_gap']:>+8.1f}%{int(r['coll_gap']):>+12,}")

    print("\n  ── 案件量掉最多 Top 10（諮詢數變少）──")
    print(f"{'律師':<10}{'5月諮詢':>8}{'前3月均':>10}{'量差':>8}{'5月簽率':>9}{'前3月簽率':>12}")
    for r in sorted(rows, key=lambda x: x["vol_gap"])[:10]:
        print(f"{r['name'][:10]:<10}{r['may_n']:>8}{r['prior_avg_n']:>10.1f}{r['vol_gap']:>+8.1f}{r['may_rate']:>8.1f}%{r['prior_rate']:>11.1f}%")

    print("\n  ── 收款落差最大 Top 10（產值掉最多）──")
    print(f"{'律師':<10}{'5月諮詢':>8}{'5月收':>12}{'前3月均收':>14}{'落差':>14}")
    for r in sorted(rows, key=lambda x: x["coll_gap"])[:10]:
        print(f"{r['name'][:10]:<10}{r['may_n']:>8}{int(r['may_coll']):>12,}{int(r['prior_avg_coll']):>14,}{int(r['coll_gap']):>+14,}")

    # ========== 4. 案型層級 ==========
    print("\n" + "=" * 76)
    print(f"4. 案型下滑：5/1–5/{CUTOFF_DAY} vs 前 3 月同期")
    print("=" * 76)
    import re
    tm = defaultdict(lambda: defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0}))
    for c in cases:
        d = parse_date(c["case_date"])
        if not d or d.day > CUTOFF_DAY: continue
        t = (c.get("case_type") or "").strip() or "(未分類)"
        t = re.split(r"[,，、]", t)[0].strip().replace("諮詢", "") or t
        m = d.strftime("%Y-%m")
        tm[t][m]["n"] += 1
        if c["is_signed"]: tm[t][m]["signed"] += 1
        tm[t][m]["collected"] += (c["collected"] or 0)

    trows = []
    for t, months in tm.items():
        may = months.get("2026-05", {"n": 0, "signed": 0, "collected": 0})
        prior_n = sum(months.get(m, {}).get("n", 0) for m in prior_months)
        prior_signed = sum(months.get(m, {}).get("signed", 0) for m in prior_months)
        prior_coll = sum(months.get(m, {}).get("collected", 0) for m in prior_months)
        if prior_n < 10 and may["n"] < 5: continue
        prior_rate = prior_signed / prior_n * 100 if prior_n else 0
        may_rate = may["signed"] / may["n"] * 100 if may["n"] else 0
        trows.append({
            "t": t,
            "may_n": may["n"], "may_rate": may_rate,
            "prior_avg_n": prior_n / 3, "prior_rate": prior_rate,
            "rate_gap": may_rate - prior_rate,
            "vol_gap": may["n"] - prior_n / 3,
            "may_coll": may["collected"],
            "prior_avg_coll": prior_coll / 3,
            "coll_gap": may["collected"] - prior_coll / 3,
        })

    print("\n  ── 簽率掉最多 Top 10 ──")
    print(f"{'案型':<14}{'5月諮詢':>8}{'5月簽率':>9}{'前3月簽率':>12}{'簽率差':>9}{'5月收':>12}{'前3月均收':>14}")
    for r in sorted(trows, key=lambda x: x["rate_gap"])[:10]:
        print(f"{r['t'][:14]:<14}{r['may_n']:>8}{r['may_rate']:>8.1f}%{r['prior_rate']:>11.1f}%{r['rate_gap']:>+8.1f}%{int(r['may_coll']):>12,}{int(r['prior_avg_coll']):>14,}")

    print("\n  ── 諮詢量掉最多 Top 10 ──")
    print(f"{'案型':<14}{'5月諮詢':>8}{'前3月均':>10}{'量差':>8}{'5月簽率':>9}{'前3月簽率':>12}")
    for r in sorted(trows, key=lambda x: x["vol_gap"])[:10]:
        print(f"{r['t'][:14]:<14}{r['may_n']:>8}{r['prior_avg_n']:>10.1f}{r['vol_gap']:>+8.1f}{r['may_rate']:>8.1f}%{r['prior_rate']:>11.1f}%")

    # ========== 5. 全所總結 ==========
    print("\n" + "=" * 76)
    print("5. 全所總結（同期 1-19）")
    print("=" * 76)
    may_n = by_month_sameperiod.get("2026-05", {}).get("n", 0)
    may_s = by_month_sameperiod.get("2026-05", {}).get("signed", 0)
    may_c = by_month_sameperiod.get("2026-05", {}).get("collected", 0)
    prior_n = sum(by_month_sameperiod.get(m, {}).get("n", 0) for m in prior_months)
    prior_s = sum(by_month_sameperiod.get(m, {}).get("signed", 0) for m in prior_months)
    prior_c = sum(by_month_sameperiod.get(m, {}).get("collected", 0) for m in prior_months)
    may_rate = may_s / may_n * 100 if may_n else 0
    prior_rate = prior_s / prior_n * 100 if prior_n else 0
    print(f"  5月 1-19 諮詢:    {may_n}   前3月同期均: {prior_n/3:.1f}   量差: {may_n - prior_n/3:+.1f}")
    print(f"  5月 1-19 簽約:    {may_s}   前3月同期均: {prior_s/3:.1f}   量差: {may_s - prior_s/3:+.1f}")
    print(f"  5月 1-19 簽率:    {may_rate:.2f}%   前3月: {prior_rate:.2f}%   差距: {may_rate - prior_rate:+.2f}%")
    print(f"  5月 1-19 收款:    {int(may_c):,}   前3月均: {int(prior_c/3):,}   落差: {int(may_c - prior_c/3):+,}")


if __name__ == "__main__":
    main()
