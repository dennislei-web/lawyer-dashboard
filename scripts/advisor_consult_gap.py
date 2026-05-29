"""
法顧諮詢後委任 — 諮詢成案歸因評估（v3，初次 / 續委任 分表）

歸因規則（使用者 2026-05-29 指定）：
  諮詢成案重點是「誰諮詢後進案」，不看後續誰承辦。
  客戶多次諮詢時，算「首次成案日之前最後一次諮詢」的諮詢者。
  金額按法顧 case_category 切兩表：
    - 初次/新案（非『續委任』）→ 計進諮詢成案
    - 續委任（既有法顧戶續約）→ 另列一表供裁示
  扣掉諮詢端已登錄收款，避免重複計（如黑熊：委任已在諮詢端 → add=0）。

唯讀，不動任何資料。
"""
import os, io, sys, re, json
from collections import defaultdict
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)
URL = os.environ["SUPABASE_URL"]; KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def fetch_all(table, select, filters=None):
    rows, off = [], 0
    while True:
        p = {"select": select, "limit": "1000", "offset": str(off)}
        if filters:
            p.update(filters)
        r = httpx.get(f"{URL}/rest/v1/{table}", params=p, headers=HDR, timeout=60)
        r.raise_for_status()
        b = r.json(); rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def norm(name):
    if not name:
        return ""
    return re.sub(r"[（(].*?[)）]", "", name).replace(" ", "").replace("　", "").strip()


def main():
    lawyers = fetch_all("lawyers", "id,name")
    lid2name = {l["id"]: l["name"] for l in lawyers}
    cc = fetch_all("consultation_cases",
                   "lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected")
    ac = fetch_all("advisor_cases",
                   "client_name,is_signed,amount_paid,paid_at,case_category")

    # 法顧已成案：分 初次 / 續委任 兩桶聚合（依 case_category）
    adv = defaultdict(lambda: {"initial": 0.0, "renewal": 0.0,
                               "init_n": 0, "renew_n": 0,
                               "first_paid": None, "cats": set()})
    for a in ac:
        if not a.get("is_signed") or (a.get("amount_paid") or 0) <= 0:
            continue
        k = norm(a["client_name"])
        cat = a.get("case_category") or "未分類"
        adv[k]["cats"].add(cat)
        if cat == "續委任":
            adv[k]["renewal"] += a["amount_paid"]; adv[k]["renew_n"] += 1
        else:
            adv[k]["initial"] += a["amount_paid"]; adv[k]["init_n"] += 1
        p = a.get("paid_at")
        if p and (adv[k]["first_paid"] is None or p < adv[k]["first_paid"]):
            adv[k]["first_paid"] = p

    consults_by_client = defaultdict(list)
    for c in cc:
        consults_by_client[norm(c["client_name"])].append(c)

    initial_rows, renewal_rows = [], []
    for k, a in adv.items():
        clist = consults_by_client.get(k, [])
        if not clist:
            continue
        anchor = a["first_paid"]
        before = [c for c in clist if c.get("case_date") and anchor and c["case_date"] <= anchor]
        if before:
            credited = max(before, key=lambda c: c["case_date"]); anomaly = False
        else:
            credited = min(clist, key=lambda c: c.get("case_date") or "9999")
            anomaly = True  # 諮詢晚於成案 / 無成案日 → 不是這次諮詢造成進案
        lid = credited["lawyer_id"]
        already = sum(c.get("collected") or 0 for c in clist if c["lawyer_id"] == lid)
        client_disp = max((c["client_name"] for c in clist), key=len)
        base = {
            "lawyer": lid2name.get(lid, lid),
            "lawyer_id": lid,
            "client": client_disp,
            "client_norm": k,
            "credit_case_number": credited.get("case_number"),
            "credit_row_collected": credited.get("collected") or 0,
            "credit_row_revenue": credited.get("revenue") or 0,
            "credit_month": (credited.get("case_date") or "")[:7],
            "first_paid": anchor,
            "credit_consult_date": credited.get("case_date"),
            "credit_consult_type": credited.get("case_type"),
            "consult_collected_already": already,
            "adv_categories": sorted(a["cats"]),
            "anomaly_consult_after_signing": anomaly,
        }
        # 扣諮詢端已登錄收款：先扣初次、溢出再扣續委任（避免重複計如黑熊）
        remaining = already
        init_add = max(0, a["initial"] - remaining)
        remaining = max(0, remaining - a["initial"])
        renew_add = max(0, a["renewal"] - remaining)
        if init_add > 0:
            r = dict(base); r.update({"advisor_initial": a["initial"],
                                      "add_to_consult_revenue": init_add,
                                      "advisor_case_n": a["init_n"]})
            initial_rows.append(r)
        if renew_add > 0:
            r = dict(base); r.update({"advisor_renewal": a["renewal"],
                                      "add_to_consult_revenue": renew_add,
                                      "advisor_case_n": a["renew_n"]})
            renewal_rows.append(r)

    initial_rows.sort(key=lambda x: -x["add_to_consult_revenue"])
    renewal_rows.sort(key=lambda x: -x["add_to_consult_revenue"])

    def summarize(rows, title, drop_anomaly=False):
        use = [r for r in rows if not (drop_anomaly and r["anomaly_consult_after_signing"])]
        bl = defaultdict(lambda: [0.0, 0])
        for r in use:
            bl[r["lawyer"]][0] += r["add_to_consult_revenue"]; bl[r["lawyer"]][1] += 1
        total = sum(r["add_to_consult_revenue"] for r in use)
        print("\n" + "=" * 76)
        print(f"{title} | 律師 {len(bl)} 位 | 客戶 {len(use)} | 合計 {total:,.0f}")
        print("=" * 76)
        print(f"{'律師':<8}{'金額':>12}{'筆數':>6}")
        for n, (amt, c) in sorted(bl.items(), key=lambda kv: -kv[1][0]):
            print(f"{n:<8}{amt:>12,.0f}{c:>6}")
        print("--- 明細 ---")
        for r in use:
            fl = " ⚠諮詢晚於成案" if r["anomaly_consult_after_signing"] else ""
            print(f"  {r['lawyer']:<5}|{r['client'][:22]:<22}|成案{r['first_paid'] or '—'}|諮詢{r['credit_consult_date'] or '—'}({(r['credit_consult_type'] or '')[:10]})|金額{r['add_to_consult_revenue']:>8,.0f}|已收{r['consult_collected_already']:>7,.0f}{fl}")
        return total

    # 初次：排除「諮詢晚於成案」異常
    t_init = summarize(initial_rows, "表一【初次諮詢進案 — 計進諮詢成案】（已排除諮詢晚於成案的異常）", drop_anomaly=True)
    t_renew = summarize(renewal_rows, "表二【續委任 — 另列供裁示，未計入】", drop_anomaly=False)

    out = {
        "rule": "成案前最後一次諮詢者；初次/續委任依 advisor_cases.case_category 切；初次扣諮詢端已收",
        "table1_initial": {"total": t_init, "rows": [r for r in initial_rows if not r["anomaly_consult_after_signing"]],
                           "excluded_anomaly": [r for r in initial_rows if r["anomaly_consult_after_signing"]]},
        "table2_renewal": {"total": t_renew, "rows": renewal_rows},
    }
    outp = SCRIPT_DIR / "briefs" / "raw_data" / "advisor_consult_gap.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入：{outp}")

    # ── 產出 pipeline 用的 credits 檔（只含表一：初次、非異常、add>0） ──
    # daily_update / 一次性 apply 會讀此檔，把 add_amount 加到「被認定的那次諮詢」
    # consultation_cases 列的 collected/revenue 上，並同步 monthly_stats。
    credits = []
    for r in initial_rows:
        if r["anomaly_consult_after_signing"]:
            continue
        credits.append({
            "lawyer_id": r["lawyer_id"],
            "lawyer": r["lawyer"],
            "client": r["client"],
            "client_norm": r["client_norm"],
            "case_number": r["credit_case_number"],
            "case_date": r["credit_consult_date"],
            "month": r["credit_month"],
            "add_amount": r["add_to_consult_revenue"],
            "base_collected": r["credit_row_collected"],
            "base_revenue": r["credit_row_revenue"],
        })
    credits_out = {
        "note": "法顧初次諮詢進案 → 計進諮詢律師成案金額（表一）。add_amount 已扣諮詢端既有收款。",
        "generated_total": sum(c["add_amount"] for c in credits),
        "count": len(credits),
        "credits": credits,
    }
    creditp = SCRIPT_DIR / "briefs" / "raw_data" / "advisor_consult_credits.json"
    creditp.write_text(json.dumps(credits_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫入：{creditp}（{len(credits)} 筆，合計 {credits_out['generated_total']:,.0f}）")


if __name__ == "__main__":
    main()
