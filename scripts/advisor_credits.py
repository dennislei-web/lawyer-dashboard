"""法顧初次諮詢進案 → 計進諮詢律師成案金額（表一 credits）。

來源檔：briefs/raw_data/advisor_consult_credits.json（由 advisor_consult_gap.py 產出）。
規則：法顧的委任費走 advisor_cases/advisor_transactions，不在 consultation_cases，
諮詢律師原本拿不到這筆「諮詢成案金額」。此模組把每筆 add_amount（已扣諮詢端既有收款）
加回「成案前最後一次諮詢」那列 consultation_cases 的 collected/revenue，並同步 monthly_stats。

只含表一（初次/新案），續委任（表二）不計入。

設計為「加性、在 upsert 前套用」：daily_update 每次從 CRM xlsx 重建 base 後 +credit 再 upsert
（merge-duplicates 絕對覆寫），所以重複跑也只會是 base+credit，天然 idempotent。
"""
import os
import re
import json
from pathlib import Path
from collections import defaultdict

_SCRIPT_DIR = Path(__file__).parent.resolve()
_CREDITS_PATH = _SCRIPT_DIR / "briefs" / "raw_data" / "advisor_consult_credits.json"


def _norm(name):
    if not name:
        return ""
    return re.sub(r"[（(].*?[)）]", "", name).replace(" ", "").replace("　", "").strip()


def load_credits():
    """回傳 credits list；檔案不存在則回傳空 list（pipeline 不應因此中斷）。"""
    if not _CREDITS_PATH.exists():
        return []
    data = json.loads(_CREDITS_PATH.read_text(encoding="utf-8"))
    return data.get("credits", [])


def _credit_index_by_case(credits):
    idx = defaultdict(float)
    for c in credits:
        if c.get("case_number"):
            idx[str(c["case_number"]).strip()] += c["add_amount"]
    return idx


def _credit_index_by_triple(credits):
    """key = (lawyer_id, case_date, client_norm) → 累加 add_amount。"""
    idx = defaultdict(float)
    for c in credits:
        key = (c["lawyer_id"], c.get("case_date"), c.get("client_norm") or _norm(c.get("client")))
        idx[key] += c["add_amount"]
    return idx


def _credit_index_by_month(credits):
    idx = defaultdict(float)
    for c in credits:
        idx[(c["lawyer_id"], c.get("month"))] += c["add_amount"]
    return idx


def bump_consultation_cases(case_rows, credits=None):
    """就地把 credit 加到對應 consultation_cases dict 列的 collected/revenue。

    先以 case_number 配對（最精確）；該列不在本批時，退而用
    (lawyer_id, case_date, client_norm) 配對。回傳 (matched_amount, n_rows)。
    """
    if credits is None:
        credits = load_credits()
    if not credits:
        return 0.0, 0

    by_case = _credit_index_by_case(credits)
    by_triple = _credit_index_by_triple(credits)
    matched_amt = 0.0
    matched_n = 0
    seen_triples = set()

    for r in case_rows:
        cn = str(r.get("case_number") or "").strip()
        add = 0.0
        if cn and cn in by_case:
            add = by_case[cn]
        else:
            key = (r.get("lawyer_id"), r.get("case_date"), _norm(r.get("client_name")))
            if key in by_triple and key not in seen_triples:
                add = by_triple[key]
                seen_triples.add(key)
        if add:
            r["collected"] = (r.get("collected") or 0) + int(round(add))
            r["revenue"] = (r.get("revenue") or 0) + int(round(add))
            matched_amt += add
            matched_n += 1
    return matched_amt, matched_n


def bump_monthly_stats(rows, credits=None):
    """就地把 credit 依 (lawyer_id, month) 加到 monthly_stats dict 列的 collected/revenue。

    rows 內若沒有對應 (lawyer_id, month) 列則略過（該律師當月若無諮詢，credit 會在
    rebuild_monthly_stats 經 consultation_cases 重建時補上）。回傳 (matched_amount, n_rows)。
    """
    if credits is None:
        credits = load_credits()
    if not credits:
        return 0.0, 0

    by_month = _credit_index_by_month(credits)
    matched_amt = 0.0
    matched_n = 0
    for r in rows:
        key = (r.get("lawyer_id"), r.get("month"))
        add = by_month.get(key)
        if add:
            r["collected"] = (r.get("collected") or 0) + int(round(add))
            r["revenue"] = (r.get("revenue") or 0) + int(round(add))
            matched_amt += add
            matched_n += 1
    return matched_amt, matched_n
