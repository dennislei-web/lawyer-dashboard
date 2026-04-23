"""
Wave 2 Step 1：抽取律師 1-on-1 會議所需資料
- 輸入：律師姓名
- 輸出：briefs/raw_data/{律師名}_prep.json

唯讀，不動任何資料。
"""
import os, io, sys, re, json, argparse
from pathlib import Path
from collections import defaultdict
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def fetch_all(table, select, order=None, filters=None):
    rows, off, page = [], 0, 1000
    while True:
        params = {"select": select, "limit": str(page), "offset": str(off)}
        if order:
            params["order"] = order
        if filters:
            params.update(filters)
        r = httpx.get(f"{URL}/rest/v1/{table}", params=params, headers=HDR, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        off += page
    return rows


# 諮詢型態 — 這是「如何諮詢」的維度，不是案件實質內容
CONSULT_METHODS = {"現場諮詢", "視訊諮詢", "電話諮詢"}


def extract_consult_method(t):
    """
    從 case_type 欄位抽出「諮詢型態」維度。
    例:
      '現場諮詢, 支付命令' → '現場'
      '視訊諮詢'           → '視訊'
      '民事一審'           → '(未標記)'
      None / ''            → '(未標記)'
    """
    if not t or not t.strip():
        return "(未標記)"
    parts = [p.strip() for p in re.split(r"[,，、]", t) if p.strip()]
    for p in parts:
        if p in CONSULT_METHODS:
            return p.replace("諮詢", "")  # 現場諮詢→現場
    return "(未標記)"


def extract_case_content(t):
    """
    從 case_type 欄位抽出「案件實質內容」維度（支付命令、民事一審等）。
    若只有諮詢型態沒實質內容 → '(未指定案件內容)'。
    例:
      '現場諮詢, 支付命令' → '支付命令'
      '現場諮詢'           → '(未指定案件內容)'
      '視訊諮詢, 民事一審' → '民事一審'
      None / ''            → '(未指定案件內容)'
    """
    if not t or not t.strip():
        return "(未指定案件內容)"
    parts = [p.strip() for p in re.split(r"[,，、]", t) if p.strip()]
    real = [p for p in parts if p not in CONSULT_METHODS]
    if real:
        return real[0]
    return "(未指定案件內容)"


# 向後相容別名（build_brief_pdf.py 仍引用）
def clean_case_type(t):
    return extract_case_content(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="律師姓名（例：洪琬琪）")
    ap.add_argument("--output-dir", default=str(SCRIPT_DIR / "briefs" / "raw_data"))
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 找律師
    lawyers = fetch_all("lawyers", "id,name,office,is_active,role")
    target = next((l for l in lawyers if l["name"] == args.name), None)
    if not target:
        print(f"找不到律師：{args.name}")
        print(f"可用姓名：{sorted(l['name'] for l in lawyers)[:20]}...")
        sys.exit(1)
    print(f"律師：{target['name']} ({target['id']})")

    # Step 2: 抽全所資料（算基準用）
    print("[抓資料]")
    all_stats = fetch_all("monthly_stats", "lawyer_id,month,consult_count,signed_count,revenue,collected")
    all_cases = fetch_all(
        "consultation_cases",
        "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected,meeting_record,transcript,lawyer_notes,tracking_staff,tracking_notes,tracking_status",
        order="case_date.desc",
    )
    print(f"  monthly_stats={len(all_stats)}  cases={len(all_cases)}")

    # Step 3: 全所 case_type 基準（n >= 5 的類型）
    type_agg = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in all_cases:
        t = clean_case_type(c.get("case_type"))
        type_agg[t]["n"] += 1
        if c.get("is_signed"):
            type_agg[t]["signed"] += 1
        type_agg[t]["collected"] += (c.get("collected") or 0)
    type_baseline = {
        t: {
            "n": d["n"],
            "sign_rate": d["signed"] / d["n"] * 100 if d["n"] else 0,
            "avg_collected": d["collected"] / d["signed"] if d["signed"] else 0,
            "consult_eff": d["collected"] / d["n"] if d["n"] else 0,
        }
        for t, d in type_agg.items() if d["n"] >= 5
    }

    # Step 3b: 同所別 case_type 基準（避免合署律師拉高/拉低 baseline）
    # 建 lawyer_id → office lookup
    lid_to_office = {l["id"]: (l.get("office") or "(無)") for l in lawyers}
    target_office = target.get("office") or "(無)"
    office_case_filter = lambda c: lid_to_office.get(c["lawyer_id"]) == target_office
    office_cases = [c for c in all_cases if office_case_filter(c)]
    office_stats = [s for s in all_stats if lid_to_office.get(s["lawyer_id"]) == target_office]
    office_lawyer_ids = {lid for lid, o in lid_to_office.items() if o == target_office}

    office_type_agg = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in office_cases:
        t = clean_case_type(c.get("case_type"))
        office_type_agg[t]["n"] += 1
        if c.get("is_signed"):
            office_type_agg[t]["signed"] += 1
        office_type_agg[t]["collected"] += (c.get("collected") or 0)
    office_type_baseline = {
        t: {
            "n": d["n"],
            "sign_rate": d["signed"] / d["n"] * 100 if d["n"] else 0,
            "avg_collected": d["collected"] / d["signed"] if d["signed"] else 0,
            "consult_eff": d["collected"] / d["n"] if d["n"] else 0,
        }
        for t, d in office_type_agg.items() if d["n"] >= 5
    }
    print(f"  同所別「{target_office}」律師 {len(office_lawyer_ids)} 位、案件 {len(office_cases)}")

    # Step 4: 這位律師的 stats + cases
    lid = target["id"]
    my_stats = [s for s in all_stats if s["lawyer_id"] == lid]
    my_cases = [c for c in all_cases if c["lawyer_id"] == lid]
    my_stats.sort(key=lambda s: s["month"])

    # 整體數字
    total_consult = sum(s.get("consult_count") or 0 for s in my_stats)
    total_signed = sum(s.get("signed_count") or 0 for s in my_stats)
    total_collected = sum(s.get("collected") or 0 for s in my_stats)
    all_total_consult = sum(s.get("consult_count") or 0 for s in all_stats)
    all_total_signed = sum(s.get("signed_count") or 0 for s in all_stats)
    all_total_collected = sum(s.get("collected") or 0 for s in all_stats)
    firm_sign_rate = all_total_signed / all_total_consult * 100 if all_total_consult else 0
    firm_eff = all_total_collected / all_total_consult if all_total_consult else 0
    firm_avg_unit = all_total_collected / all_total_signed if all_total_signed else 0

    # 同所別基準（不含本律師，避免自己影響 baseline）
    office_stats_ex = [s for s in office_stats if s["lawyer_id"] != lid]
    off_total_consult = sum(s.get("consult_count") or 0 for s in office_stats_ex)
    off_total_signed = sum(s.get("signed_count") or 0 for s in office_stats_ex)
    off_total_collected = sum(s.get("collected") or 0 for s in office_stats_ex)
    office_sign_rate = off_total_signed / off_total_consult * 100 if off_total_consult else 0
    office_eff = off_total_collected / off_total_consult if off_total_consult else 0
    office_avg_unit = off_total_collected / off_total_signed if off_total_signed else 0

    overall = {
        "consult_count": total_consult,
        "signed_count": total_signed,
        "sign_rate": total_signed / total_consult * 100 if total_consult else 0,
        "collected": total_collected,
        "avg_collected": total_collected / total_signed if total_signed else 0,
        "consult_eff": total_collected / total_consult if total_consult else 0,
        # 全所基準
        "firm_sign_rate": firm_sign_rate,
        "firm_eff": firm_eff,
        "firm_avg_unit": firm_avg_unit,
        # 同所別基準（不含本人）
        "office": target_office,
        "office_peer_count": len(office_lawyer_ids) - 1,  # 扣掉本人
        "office_sign_rate": office_sign_rate,
        "office_eff": office_eff,
        "office_avg_unit": office_avg_unit,
    }

    # 近 3 月 vs 前 3 月
    all_months = sorted({s["month"] for s in all_stats})
    recent3 = all_months[-3:]
    prev3 = all_months[-6:-3]

    def agg_period(stats_subset, months_list):
        c = sum(s.get("consult_count") or 0 for s in stats_subset if s["month"] in months_list)
        sg = sum(s.get("signed_count") or 0 for s in stats_subset if s["month"] in months_list)
        co = sum(s.get("collected") or 0 for s in stats_subset if s["month"] in months_list)
        return {
            "consult_count": c,
            "signed_count": sg,
            "sign_rate": sg / c * 100 if c else 0,
            "collected": co,
            "consult_eff": co / c if c else 0,
        }

    recent_agg = agg_period(my_stats, recent3)
    prev_agg = agg_period(my_stats, prev3)

    # 按月趨勢（最近 12 個月）
    last12_months = all_months[-12:]
    monthly_trend = []
    for m in last12_months:
        s = next((x for x in my_stats if x["month"] == m), None)
        c = s.get("consult_count") if s else 0
        sg = s.get("signed_count") if s else 0
        co = s.get("collected") if s else 0
        monthly_trend.append({
            "month": m,
            "consult_count": c or 0,
            "signed_count": sg or 0,
            "sign_rate": (sg / c * 100) if (s and c) else 0,
            "collected": co or 0,
        })

    # Step 5: 個人 × case_type 錯配
    my_type_agg = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in my_cases:
        t = clean_case_type(c.get("case_type"))
        my_type_agg[t]["n"] += 1
        if c.get("is_signed"):
            my_type_agg[t]["signed"] += 1
        my_type_agg[t]["collected"] += (c.get("collected") or 0)

    # Step 5a: 近一季（recent 3 months）vs 更早（earlier periods）的每 case_type 分段數據
    # 用 case_date 切：recent_date_cutoff 以後為「近一季」，以前為「更早」
    recent_cutoff_ym = recent3[0] if recent3 else None
    recent_cutoff_date = f"{recent_cutoff_ym}-01" if recent_cutoff_ym else None

    my_type_recent = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    my_type_earlier = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in my_cases:
        t = clean_case_type(c.get("case_type"))
        bucket = my_type_recent if (recent_cutoff_date and c.get("case_date") and c["case_date"] >= recent_cutoff_date) else my_type_earlier
        bucket[t]["n"] += 1
        if c.get("is_signed"):
            bucket[t]["signed"] += 1
        bucket[t]["collected"] += (c.get("collected") or 0)

    def _trend_for_type(t):
        """給定 case_type，回傳近一季 vs 更早的比較資料 + 趨勢標籤。
        注意小樣本：r_signed < 3 或 e_signed < 3 時標「樣本小」，讓讀者知道 delta 可能是雜訊。"""
        r = my_type_recent.get(t, {"n": 0, "signed": 0, "collected": 0})
        e = my_type_earlier.get(t, {"n": 0, "signed": 0, "collected": 0})
        r_unit = r["collected"] / r["signed"] if r["signed"] else None
        e_unit = e["collected"] / e["signed"] if e["signed"] else None
        r_rate = r["signed"] / r["n"] * 100 if r["n"] else None
        e_rate = e["signed"] / e["n"] * 100 if e["n"] else None
        small_sample = (r["signed"] < 3) or (e["signed"] < 3)
        # 趨勢標籤：以客單價為主，件數太少就標樣本小
        if r["signed"] == 0:
            label = "近一季無已簽"
        elif e["signed"] == 0:
            label = "新成長案型"
        else:
            pct = (r_unit - e_unit) / e_unit * 100 if e_unit else 0
            # 小樣本時放寬門檻，標明樣本小
            if pct >= 10:
                label = "變好"
            elif pct <= -10:
                label = "變差"
            else:
                label = "持平"
            if small_sample:
                label += "（樣本小）"
        return {
            "recent_n": r["n"], "recent_signed": r["signed"],
            "recent_avg_collected": r_unit,
            "recent_sign_rate": r_rate,
            "earlier_n": e["n"], "earlier_signed": e["signed"],
            "earlier_avg_collected": e_unit,
            "earlier_sign_rate": e_rate,
            "unit_delta_pct": (
                (r_unit - e_unit) / e_unit * 100
                if (r_unit is not None and e_unit)
                else None
            ),
            "trend_label": label,
            "small_sample": small_sample,
        }

    # 重要：律師只對已成案案件補填具體案件內容 → 用「成案率」做 gap 會是 artifact
    # 改用「已成案客單價」做 gap，只看已簽約案件（客單價的分母、分子都可靠）
    gaps = []
    for t, d in my_type_agg.items():
        # 排除「(未指定案件內容)」+ 要求已簽 >= 5 才有樣本意義
        if d["signed"] < 5 or t not in type_baseline or t == "(未指定案件內容)":
            continue
        base_unit = type_baseline[t]["avg_collected"]  # 全所該類別平均已成案客單價
        if base_unit <= 0:
            continue
        my_unit = d["collected"] / d["signed"]
        unit_gap = my_unit - base_unit
        unit_gap_pct = unit_gap / base_unit * 100

        # 同所別基準（若該 case_type 在同所別樣本 >= 5 才算）
        off_base = office_type_baseline.get(t, {})
        off_base_unit = off_base.get("avg_collected", 0)
        if off_base_unit > 0:
            office_unit_gap = my_unit - off_base_unit
            office_unit_gap_pct = office_unit_gap / off_base_unit * 100
            office_n = off_base.get("n", 0)
        else:
            office_unit_gap = None
            office_unit_gap_pct = None
            office_n = off_base.get("n", 0)  # 可能為 0 或小於 5

        gaps.append({
            "case_type": t,
            "n": d["n"],                    # 登錄為此類別的總件數（幾乎等於已簽）
            "my_signed": d["signed"],       # 已簽案件數
            "my_avg_collected": my_unit,    # 已成案客單價
            # 全所 baseline
            "baseline_avg_collected": base_unit,
            "unit_gap": unit_gap,
            "unit_gap_pct": unit_gap_pct,
            # 同所別 baseline（不含合署/司法官合署等不同類型所）
            "office_baseline_avg_collected": off_base_unit if off_base_unit > 0 else None,
            "office_baseline_n": office_n,
            "office_unit_gap": office_unit_gap,
            "office_unit_gap_pct": office_unit_gap_pct,
            # 保留供參考（但不用排序，因為是 artifact）
            "my_sign_rate": d["signed"] / d["n"] * 100 if d["n"] else 0,
            "baseline_sign_rate": type_baseline[t]["sign_rate"],
            # 近一季 vs 更早 的趨勢資料
            "trend": _trend_for_type(t),
        })

    strengths = sorted([g for g in gaps if g["unit_gap_pct"] > 0], key=lambda x: -x["unit_gap_pct"])[:5]
    weaknesses = sorted([g for g in gaps if g["unit_gap_pct"] < 0], key=lambda x: x["unit_gap_pct"])[:5]

    # Step 5.5: 諮詢型態（現場/視訊/電話）— 另一個維度分析
    # 全所基準
    method_all_agg = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in all_cases:
        m = extract_consult_method(c.get("case_type"))
        method_all_agg[m]["n"] += 1
        if c.get("is_signed"):
            method_all_agg[m]["signed"] += 1
        method_all_agg[m]["collected"] += (c.get("collected") or 0)
    method_baseline = {
        m: {
            "n": d["n"],
            "sign_rate": d["signed"] / d["n"] * 100 if d["n"] else 0,
            "consult_eff": d["collected"] / d["n"] if d["n"] else 0,
        }
        for m, d in method_all_agg.items()
    }
    # 律師個人
    method_my_agg = defaultdict(lambda: {"n": 0, "signed": 0, "collected": 0})
    for c in my_cases:
        m = extract_consult_method(c.get("case_type"))
        method_my_agg[m]["n"] += 1
        if c.get("is_signed"):
            method_my_agg[m]["signed"] += 1
        method_my_agg[m]["collected"] += (c.get("collected") or 0)
    consult_method_stats = []
    for m, d in sorted(method_my_agg.items(), key=lambda kv: -kv[1]["n"]):
        if d["n"] < 3:
            continue
        my_rate = d["signed"] / d["n"] * 100
        my_eff = d["collected"] / d["n"] if d["n"] else 0
        base = method_baseline.get(m, {})
        consult_method_stats.append({
            "method": m,
            "n": d["n"],
            "my_signed": d["signed"],
            "my_sign_rate": my_rate,
            "my_consult_eff": my_eff,
            "baseline_sign_rate": base.get("sign_rate"),
            "baseline_consult_eff": base.get("consult_eff"),
            "sign_rate_gap": (my_rate - base["sign_rate"]) if base.get("sign_rate") is not None else None,
            "eff_gap": (my_eff - base["consult_eff"]) if base.get("consult_eff") is not None else None,
        })

    # Step 6: 近 3 個月所有 case（按是否有 meeting_record 標註）
    # 用 case_date 而不是 month 字串比對（cases.case_date 是 DATE）
    recent_date_cutoff = None
    if recent3:
        first_m = recent3[0]  # 例 '2026-02'
        recent_date_cutoff = first_m + "-01"
    recent_cases = [
        c for c in my_cases
        if recent_date_cutoff and c.get("case_date") and c["case_date"] >= recent_date_cutoff
    ]
    recent_cases.sort(key=lambda c: c.get("case_date") or "", reverse=True)

    # 標哪些有 meeting_record、哪些沒
    recent_with_mr = [c for c in recent_cases if c.get("meeting_record")]
    recent_no_mr = [c for c in recent_cases if not c.get("meeting_record")]

    # Step 7: 所有有會議記錄的案件（不限近 3 月，樣本湊多一點給 LLM）
    all_mr_cases = [c for c in my_cases if c.get("meeting_record")]
    all_mr_cases.sort(key=lambda c: c.get("case_date") or "", reverse=True)

    # 輸出
    output = {
        "lawyer": target,
        "overall": overall,
        "recent3_months": recent3,
        "prev3_months": prev3,
        "recent_agg": recent_agg,
        "prev_agg": prev_agg,
        "period_delta": {
            "sign_rate_delta": recent_agg["sign_rate"] - prev_agg["sign_rate"],
            "consult_eff_delta": recent_agg["consult_eff"] - prev_agg["consult_eff"],
        },
        "monthly_trend": monthly_trend,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "consult_method_stats": consult_method_stats,
        "recent_cases_summary": {
            "total": len(recent_cases),
            "signed": sum(1 for c in recent_cases if c.get("is_signed")),
            "unsigned": sum(1 for c in recent_cases if not c.get("is_signed")),
            "with_mr": len(recent_with_mr),
            "no_mr": len(recent_no_mr),
        },
        "cases_with_meeting_record": [
            {
                "id": c["id"],
                "case_date": c.get("case_date"),
                "case_type": c.get("case_type"),
                "case_number": c.get("case_number"),
                "client_name": c.get("client_name"),
                "is_signed": c.get("is_signed"),
                "revenue": c.get("revenue"),
                "collected": c.get("collected"),
                "meeting_record": c.get("meeting_record"),
                "transcript": c.get("transcript"),
                "lawyer_notes": c.get("lawyer_notes"),
            }
            for c in all_mr_cases
        ],
        "_metadata": {
            "total_my_cases": len(my_cases),
            "cases_with_mr_count": len(all_mr_cases),
            "data_snapshot": f"{all_months[0]} ~ {all_months[-1]}" if all_months else "",
        },
    }

    out_path = out_dir / f"{target['name']}_prep.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入：{out_path}")
    print(f"  整體 consult={overall['consult_count']}, signed={overall['signed_count']}, sign_rate={overall['sign_rate']:.1f}%")
    print(f"  近3月 vs 前3月 sign_rate: {recent_agg['sign_rate']:.1f}% vs {prev_agg['sign_rate']:.1f}% (Δ {output['period_delta']['sign_rate_delta']:+.1f}pp)")
    print(f"  強項: {len(strengths)} 類, 弱項: {len(weaknesses)} 類")
    print(f"  有會議記錄案件: {len(all_mr_cases)}")


if __name__ == "__main__":
    main()
