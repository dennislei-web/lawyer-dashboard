"""
法顧諮詢後委任 — 諮詢成案歸因評估（v4，合併口徑）

歸因規則（使用者 2026-05-29 指定、2026-05-29 修正）：
  諮詢成案重點是「誰諮詢後進案」，不看後續誰承辦。
  客戶多次諮詢時，算「首次成案日之前最後一次諮詢」的諮詢者。
  「諮詢後委任」一律計進諮詢律師成案金額，不分初次/續委任：
    advisor_cases.case_category 的『續委任』在資料裡其實是「諮詢後的委任那一腿」
    （dual-leg 帳務：諮詢費 + 委任費），不是『既有法顧戶續約』，故不可拿來排除。
    驗證：被排除的續委任列在 credited 諮詢日前皆無任何法顧簽案/儲值歷史。
  扣掉諮詢端已登錄收款，避免重複計（如黑熊：委任已在諮詢端 → add=0）。
  排除「諮詢晚於成案 / 無成案日」的 anomaly（非該次諮詢造成進案）。

唯讀 DB；但會（重新）產出 credits 檔。為避免重算時把已 materialize 的 credit
誤當諮詢端已收，會先讀既有 credits 檔，把先前 add 從 collected 還原（fixpoint）。
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
CREDITS_PATH = SCRIPT_DIR / "briefs" / "raw_data" / "advisor_consult_credits.json"
# 由 apply_advisor_credits.py 寫入 / 還原時刪除：存在 ⟺ DB 目前已套用 credit。
MATERIALIZED_MARKER = SCRIPT_DIR / "briefs" / "raw_data" / ".advisor_credits_monthly_applied.json"


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


def _load_prev_credits():
    """讀既有 credits 檔，回傳 (by_norm 累加 add, by_case add)；
    讓本次重算把先前已加進 DB 的 credit 還原回 base（fixpoint）。

    只有當 materialization marker 存在（DB 目前確實已套用 credit）才還原；
    否則回傳空 map，避免在 base（未套用）狀態下重複扣減而灌大金額。"""
    by_norm, by_case = defaultdict(float), defaultdict(float)
    if CREDITS_PATH.exists() and MATERIALIZED_MARKER.exists():
        for c in json.loads(CREDITS_PATH.read_text(encoding="utf-8")).get("credits", []):
            by_norm[c.get("client_norm")] += c.get("add_amount", 0)
            if c.get("case_number"):
                by_case[str(c["case_number"]).strip()] += c.get("add_amount", 0)
    return by_norm, by_case


def main():
    prev_by_norm, prev_by_case = _load_prev_credits()

    lawyers = fetch_all("lawyers", "id,name")
    lid2name = {l["id"]: l["name"] for l in lawyers}
    cc = fetch_all("consultation_cases",
                   "lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected")
    ac = fetch_all("advisor_cases",
                   "client_name,is_signed,amount_paid,paid_at,case_category")

    # 法顧已成案：每客戶聚合 signed 總額（不分 case_category）
    adv = defaultdict(lambda: {"tot": 0.0, "n": 0, "first_paid": None, "cats": set()})
    for a in ac:
        if not a.get("is_signed") or (a.get("amount_paid") or 0) <= 0:
            continue
        k = norm(a["client_name"])
        adv[k]["tot"] += a["amount_paid"]; adv[k]["n"] += 1
        adv[k]["cats"].add(a.get("case_category") or "未分類")
        p = a.get("paid_at")
        if p and (adv[k]["first_paid"] is None or p < adv[k]["first_paid"]):
            adv[k]["first_paid"] = p

    consults_by_client = defaultdict(list)
    for c in cc:
        consults_by_client[norm(c["client_name"])].append(c)

    rows = []
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
        # 諮詢端已收：扣掉先前已 materialize 的 credit（fixpoint），還原成真實諮詢收款
        already_raw = sum(c.get("collected") or 0 for c in clist if c["lawyer_id"] == lid)
        already = max(0, already_raw - prev_by_norm.get(k, 0))
        add = max(0, a["tot"] - already)
        # credited 列的真實 base（扣掉這列先前加的 credit）
        cn = credited.get("case_number")
        row_credit = prev_by_case.get(str(cn).strip(), 0) if cn else 0
        base_collected = max(0, (credited.get("collected") or 0) - row_credit)
        base_revenue = max(0, (credited.get("revenue") or 0) - row_credit)
        client_disp = max((c["client_name"] for c in clist), key=len)
        rows.append({
            "lawyer": lid2name.get(lid, lid),
            "lawyer_id": lid,
            "client": client_disp,
            "client_norm": k,
            "case_number": cn,
            "case_date": credited.get("case_date"),
            "credit_consult_type": credited.get("case_type"),
            "month": (credited.get("case_date") or "")[:7],
            "first_paid": anchor,
            "advisor_total_signed": a["tot"],
            "advisor_case_n": a["n"],
            "consult_collected_already": already,
            "add_amount": add,
            "base_collected": base_collected,
            "base_revenue": base_revenue,
            "adv_categories": sorted(a["cats"]),
            "anomaly_consult_after_signing": anomaly,
        })

    counted = [r for r in rows if not r["anomaly_consult_after_signing"] and r["add_amount"] > 0]
    anomalies = [r for r in rows if r["anomaly_consult_after_signing"] and r["add_amount"] > 0]
    counted.sort(key=lambda x: -x["add_amount"])

    bl = defaultdict(lambda: [0.0, 0])
    for r in counted:
        bl[r["lawyer"]][0] += r["add_amount"]; bl[r["lawyer"]][1] += 1
    total = sum(r["add_amount"] for r in counted)
    print("\n" + "=" * 84)
    print(f"法顧諮詢後委任 → 計進諮詢律師成案金額（合併口徑） | 律師 {len(bl)} | 客戶 {len(counted)} | 合計 {total:,.0f}")
    print("=" * 84)
    print(f"{'律師':<8}{'金額':>12}{'筆數':>6}")
    for n, (amt, c) in sorted(bl.items(), key=lambda kv: -kv[1][0]):
        print(f"{n:<8}{amt:>12,.0f}{c:>6}")
    print("--- 明細 ---")
    for r in counted:
        print(f"  {r['lawyer']:<5}|{r['client'][:22]:<22}|成案{r['first_paid'] or '—'}"
              f"|諮詢{r['case_date'] or '—'}({(r['credit_consult_type'] or '')[:10]})"
              f"|加{r['add_amount']:>8,.0f}|已收{r['consult_collected_already']:>7,.0f}|cat={','.join(r['adv_categories'])}")
    print(f"\n（排除 諮詢晚於成案/無成案日 anomaly：{len(anomalies)} 位）")

    out = {
        "rule": "成案前最後一次諮詢者；諮詢後委任一律計入（不分 case_category）；扣諮詢端已收；排除諮詢晚於成案",
        "total": total,
        "rows": counted,
        "excluded_anomaly": anomalies,
    }
    outp = SCRIPT_DIR / "briefs" / "raw_data" / "advisor_consult_gap.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入：{outp}")

    # ── pipeline 用 credits 檔：合併口徑、非異常、add>0 ──
    credits = [{
        "lawyer_id": r["lawyer_id"], "lawyer": r["lawyer"],
        "client": r["client"], "client_norm": r["client_norm"],
        "case_number": r["case_number"], "case_date": r["case_date"],
        "month": r["month"], "add_amount": r["add_amount"],
        "base_collected": r["base_collected"], "base_revenue": r["base_revenue"],
    } for r in counted]
    credits_out = {
        "note": "法顧諮詢後委任 → 計進諮詢律師成案金額（合併口徑，不分初次/續委任）。add_amount 已扣諮詢端既有收款。",
        "generated_total": sum(c["add_amount"] for c in credits),
        "count": len(credits),
        "credits": credits,
    }
    CREDITS_PATH.write_text(json.dumps(credits_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫入：{CREDITS_PATH}（{len(credits)} 筆，合計 {credits_out['generated_total']:,.0f}）")


if __name__ == "__main__":
    main()
