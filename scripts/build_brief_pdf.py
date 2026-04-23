"""
Wave 2 Step 3：產生 1-on-1 備忘單 PDF（多頁深度報告版）
- 輸入：briefs/raw_data/{律師名}_prep.json + _llm.json
- 輸出：briefs/{律師名}_brief.pdf

每個改進建議都附：
- 建議標題
- 源案件（日期、類型、是否簽約、收款）
- reason_evidence 原文引用
- missed_opportunities / improvement_for_lawyer
"""
import os, io, sys, re, json, argparse, html
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

# Anthropic client 延遲載入（此腳本 fallback 到 rule-based 時不需要）
try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# 全域開關：是否啟用 LLM 個人化 actions（被 CLI --no-llm-actions 覆寫）
_USE_LLM_ACTIONS = True

RAW_DIR = SCRIPT_DIR / "briefs" / "raw_data"
OUT_DIR = SCRIPT_DIR / "briefs"

_URL = os.environ.get("SUPABASE_URL")
_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
_HDR = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}"} if _KEY else None


def fetch_lawyer_cases(lawyer_id):
    """拉該律師所有 case_date/case_type/is_signed/collected/client_name"""
    rows, off, page = [], 0, 1000
    while True:
        r = httpx.get(f"{_URL}/rest/v1/consultation_cases",
            params={"select": "id,case_date,case_type,case_number,is_signed,collected,client_name,lawyer_notes,tracking_notes,llm_analysis",
                    "lawyer_id": f"eq.{lawyer_id}",
                    "order": "case_date.desc",
                    "limit": str(page), "offset": str(off)},
            headers=_HDR, timeout=60)
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page: break
        off += page
    return rows


def compute_sign_lag_stats(lawyer_name, cases):
    """算簽約滯後天數分布（case_date → 第一筆 revenue_records.record_date）"""
    from collections import defaultdict
    from datetime import date

    signed = [c for c in cases if c.get("is_signed") and c.get("client_name") and c.get("case_date")]
    if not signed or not _URL:
        return None

    # 拉該律師的 revenue_records（assigned_lawyers contains 律師名）
    revs, off = [], 0
    while True:
        r = httpx.get(f"{_URL}/rest/v1/revenue_records",
            params={"select": "record_date,client_name,amount",
                    "assigned_lawyers": f"ilike.*{lawyer_name}*",
                    "order": "record_date.asc", "limit": "1000", "offset": str(off)},
            headers=_HDR, timeout=60)
        batch = r.json()
        revs.extend(batch)
        if len(batch) < 1000: break
        off += 1000

    rev_by_client = defaultdict(list)
    for rev in revs:
        if rev.get("client_name") and rev.get("record_date"):
            rev_by_client[rev["client_name"]].append(rev["record_date"])

    lags = []
    for c in signed:
        cn, cd = c["client_name"], c["case_date"]
        candidates = [d for d in rev_by_client.get(cn, []) if d >= cd]
        if candidates:
            earliest = min(candidates)
            lag = (date.fromisoformat(earliest) - date.fromisoformat(cd)).days
            lags.append(lag)

    if not lags:
        return None

    lags_sorted = sorted(lags)
    n = len(lags)
    stats = {
        "n_matched": n,
        "n_signed_total": len(signed),
        "median": lags_sorted[n // 2],
        "mean": sum(lags) / n,
        "p90": lags_sorted[int(n * 0.9)],
        "within_0": sum(1 for l in lags if l == 0) / n * 100,
        "within_7": sum(1 for l in lags if l <= 7) / n * 100,
        "within_30": sum(1 for l in lags if l <= 30) / n * 100,
        "within_60": sum(1 for l in lags if l <= 60) / n * 100,
        "within_90": sum(1 for l in lags if l <= 90) / n * 100,
        "beyond_60": sum(1 for l in lags if l > 60) / n * 100,
    }
    return stats


# 諮詢方式（不是案件類型）— 與 prep_1on1_data.py 保持一致
CONSULT_METHODS = {"現場諮詢", "視訊諮詢", "電話諮詢"}


def clean_case_type(t):
    """優先回傳真實案件類型；只有諮詢方式或空 → '(未指定案件內容)'"""
    if not t or not t.strip():
        return "(未指定案件內容)"
    parts = [p.strip() for p in re.split(r"[,，、]", t) if p.strip()]
    real = [p for p in parts if p not in CONSULT_METHODS]
    if real:
        return real[0]
    return "(未指定案件內容)"


def extract_consult_method(t):
    """與 prep_1on1_data.py 同步 — 抽諮詢型態"""
    if not t or not t.strip():
        return "(未標記)"
    parts = [p.strip() for p in re.split(r"[,，、]", t) if p.strip()]
    for p in parts:
        if p in CONSULT_METHODS:
            return p.replace("諮詢", "")
    return "(未標記)"


def compute_case_type_trends(cases, recent_cutoff):
    """切近/早兩段，按案型聚合"""
    def agg(subset):
        by = {}
        for c in subset:
            t = clean_case_type(c.get("case_type"))
            b = by.setdefault(t, {"n": 0, "s": 0, "col": 0})
            b["n"] += 1
            if c.get("is_signed"): b["s"] += 1
            b["col"] += c.get("collected") or 0
        return by

    recent = [c for c in cases if c.get("case_date") and c["case_date"] >= recent_cutoff]
    earlier = [c for c in cases if c.get("case_date") and c["case_date"] < recent_cutoff]
    return recent, earlier, agg(recent), agg(earlier)


def fmt_money(n):
    if n is None: return "—"
    return f"{int(n):,}"


def fmt_pct(n, digits=1):
    if n is None: return "—"
    return f"{n:.{digits}f}%"


def fmt_delta(n, unit="%"):
    if n is None: return "—"
    sign = "+" if n >= 0 else ""
    arrow = "↑" if n > 0 else ("↓" if n < 0 else "")
    cls = "up" if n > 0 else ("down" if n < 0 else "")
    return f'<span class="delta {cls}">{sign}{n:.1f}{unit} {arrow}</span>'


def esc(s):
    return html.escape(s or "")


# 從多個 strengths / improvements / missed_opportunities 抽主題（關鍵詞匹配）
STRENGTH_THEMES = [
    ("策略與戰術建議完整", ["策略", "戰術", "步驟", "操作", "同步", "完整", "具體", "流程"]),
    ("風險與限制提醒到位", ["風險", "注意", "提醒", "但書", "困難", "劣勢", "不利", "挑戰"]),
    ("證據蒐集指引清楚", ["證據", "蒐證", "錄音", "拍照", "舉證", "金流", "截圖", "存證"]),
    ("法律依據與程序說明", ["法條", "法律", "判例", "條文", "訴訟", "程序", "時效", "管轄"]),
    ("專業深度與案件洞察", ["專業", "深度", "洞察", "精準", "到位", "細緻", "敏銳"]),
]


def pick_top_strength_themes(signed_cases, limit=3):
    """對已簽案件的 strengths 做主題歸類，回傳 top N 主題 + 每主題的代表案例"""
    theme_hits = []
    for name, keywords in STRENGTH_THEMES:
        matches = []  # [{text, case}]
        for c in signed_cases:
            for s in c["analysis"].get("strengths") or []:
                if any(k in s for k in keywords):
                    matches.append({"text": s, "case": c})
        if matches:
            theme_hits.append({
                "name": name,
                "count": len(matches),
                "example": matches[0],
            })
    theme_hits.sort(key=lambda x: -x["count"])
    return theme_hits[:limit]


def pick_representative_improvements(unsigned_cases, limit=3):
    """從 unsigned 按 failure_reason 分組，各挑一筆最近的代表案件"""
    by_reason = {}
    for c in sorted(unsigned_cases, key=lambda x: x.get("case_date", ""), reverse=True):
        r = c["analysis"].get("failure_reason", "其他")
        if r == "已簽約":
            continue
        by_reason.setdefault(r, []).append(c)

    # 按每個 reason 案件數排序，優先從最大的 reason 挑
    sorted_reasons = sorted(by_reason.items(), key=lambda kv: -len(kv[1]))
    picks = []
    for reason, cases in sorted_reasons:
        if len(picks) >= limit:
            break
        picks.append(cases[0])
    return picks


def _try_recover_actions_json(text):
    """處理 LLM 輸出在 max_tokens 被截斷的情況。
    策略：找到 "actions": [ 開始的位置，切到最後一個完整的 }，補上 ]}。
    成功則回傳 dict，失敗回 None。"""
    try:
        i = text.find('"actions"')
        if i < 0:
            return None
        bracket_i = text.find('[', i)
        if bracket_i < 0:
            return None
        # 從頭到 bracket_i 的外層是 {"actions": [
        depth = 0
        in_str = False
        esc = False
        last_complete = -1
        for j in range(bracket_i, len(text)):
            ch = text[j]
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 1:  # 完整一個 action object 結束（深度 1 = 在 array 裡但不在 obj 裡）
                    last_complete = j
        if last_complete < 0:
            return None
        salvaged = text[:last_complete + 1] + "]}"
        return json.loads(salvaged)
    except Exception:
        return None


def generate_personalized_actions(lw, prep, llm, unsigned, signed, reason_counts, reason_total,
                                   behavior_counts, lag_stats, rec, ov, extra_fn,
                                   strengths_types, weaknesses_types, rule_based_actions):
    """
    用 LLM 根據該律師個案分析產出個人化 actions。
    失敗或被停用時回傳 rule_based_actions。

    回傳：list of {title, why, how, metric, cited_cases(optional)}
    """
    if not _USE_LLM_ACTIONS or not _ANTHROPIC_AVAILABLE:
        return rule_based_actions
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [personalized actions] 無 ANTHROPIC_API_KEY，退回 rule-based", flush=True)
        return rule_based_actions

    # 每筆案件摘要：個人化判斷所需的最精華資訊
    case_summaries = []
    for c in llm[:25]:
        client_name, case_number = extra_fn(c["case_id"])
        a = c.get("analysis") or {}
        case_summaries.append({
            "date": c.get("case_date"),
            "client": client_name or "(無)",
            "case_no": case_number or "",
            "case_type": c.get("case_type") or "",
            "signed": "簽" if c.get("is_signed") else "未簽",
            "collected": c.get("collected") or 0,
            "failure_reason": a.get("failure_reason") or "",
            "reason_evidence": (a.get("reason_evidence") or "")[:220],
            "missed_opportunities": (a.get("missed_opportunities") or [])[:5],
            "strengths": (a.get("strengths") or [])[:3],
            "improvement_for_lawyer": (a.get("improvement_for_lawyer") or "")[:450],
            "transferable_pattern": (a.get("transferable_pattern") or "")[:220],
        })

    def _pack_trend(s):
        t = s.get("trend") or {}
        return {
            "label": t.get("trend_label"),
            "recent_n": t.get("recent_n"),
            "recent_signed": t.get("recent_signed"),
            "recent_avg_unit": int(t.get("recent_avg_collected") or 0) if t.get("recent_avg_collected") else None,
            "earlier_n": t.get("earlier_n"),
            "earlier_signed": t.get("earlier_signed"),
            "earlier_avg_unit": int(t.get("earlier_avg_collected") or 0) if t.get("earlier_avg_collected") else None,
            "unit_delta_pct": round(t.get("unit_delta_pct"), 1) if t.get("unit_delta_pct") is not None else None,
            "small_sample": t.get("small_sample", False),
        }

    def _pack_item(x):
        return {
            "type": x["case_type"],
            "my_unit": int(x.get("my_avg_collected") or 0),
            "firm_base": int(x.get("baseline_avg_collected") or 0),
            "firm_gap_pct": round(x.get("unit_gap_pct") or 0, 1),
            "office_base": int(x["office_baseline_avg_collected"]) if x.get("office_baseline_avg_collected") else None,
            "office_gap_pct": round(x["office_unit_gap_pct"], 1) if x.get("office_unit_gap_pct") is not None else None,
            "office_base_n": x.get("office_baseline_n"),
            "signed": x.get("my_signed"),
            "trend": _pack_trend(x),
        }
    strengths_summary = [_pack_item(s) for s in strengths_types[:3]]
    weaknesses_summary = [_pack_item(w) for w in weaknesses_types[:3]]

    context = {
        "lawyer": lw["name"],
        "office": ov.get("office"),
        "office_peer_count": ov.get("office_peer_count"),
        "overall": {
            "consult": ov.get("consult_count"),
            "signed": ov.get("signed_count"),
            "sign_rate_pct": round(ov.get("sign_rate") or 0, 1),
            "avg_unit": int(ov.get("avg_collected") or 0),
            "consult_eff": int(ov.get("consult_eff") or 0),
            "firm_sign_rate_pct": round(ov.get("firm_sign_rate") or 0, 1),
            "firm_avg_unit": int(ov.get("firm_avg_unit") or 0),
            "firm_eff": int(ov.get("firm_eff") or 0),
            "office_sign_rate_pct": round(ov.get("office_sign_rate") or 0, 1),
            "office_avg_unit": int(ov.get("office_avg_unit") or 0),
            "office_eff": int(ov.get("office_eff") or 0),
        },
        "recent_3m": {
            "consult": rec.get("consult_count"),
            "signed": rec.get("signed_count"),
            "sign_rate_pct": round(rec.get("sign_rate") or 0, 1),
            "consult_eff": int(rec.get("consult_eff") or 0),
            "avg_unit": int((rec.get("collected") or 0) / rec["signed_count"]) if rec.get("signed_count") else 0,
        },
        "top_failure_reasons": [
            {"reason": r, "count": n, "pct": round(n / reason_total * 100) if reason_total else 0}
            for r, n in reason_counts.most_common(6) if r != "已簽約"
        ][:5],
        "behavior_breakpoints": [{"name": n, "count": c} for n, c in behavior_counts[:5]],
        "lag_stats": {
            "median_days": lag_stats.get("median") if lag_stats else None,
            "within_7_pct": round(lag_stats.get("within_7") or 0) if lag_stats else None,
            "within_30_pct": round(lag_stats.get("within_30") or 0) if lag_stats else None,
        },
        "strengths_case_types": strengths_summary,
        "weaknesses_case_types": weaknesses_summary,
        "unsigned_count": len(unsigned),
        "signed_count": len(signed),
        "cases": case_summaries,
    }

    system_prompt = (
        "你是喆律法律事務所的資深經營主管，正在為律師撰寫 1-on-1 會議的「後續行動重點」。"
        "你拿到該律師近 12 個月的整體數據、強弱項案型，以及有會議記錄的每一筆案件的 AI 個案分析。"
        "你的目標是產出**個人化、具體、可驗收**的 3-4 個 action，而不是套用放諸四海的 SOP 模板。"
    )

    user_prompt = f"""## 背景資料（JSON）

```json
{json.dumps(context, ensure_ascii=False, indent=2)}
```

## 撰寫要求

1. **每個 action 必須引用 1-3 筆具體案件**（以「2026-03-30 廖怡雯案」或「廖怡雯/胡淳為案」格式），讓律師看到馬上 recall。引用的案件要能**佐證這個 action 的必要性**。
2. **根據律師真實數據選題**，不要每個律師都產一樣的 action：
   - 若弱項案型客單價顯著低於基準 → 一個 action 針對該案型給策略
   - 若強項案型表現好 → 一個 action 講 cross-sell / 深耕
   - Top 失敗原因各別處理，不要合併（例如「決策延遲」和「個人因素」應拆兩個 action）
   - 行為斷點引用具體案件的 reason_evidence 或 missed_opportunities 原文
3. **善用「同所別 baseline」** — 每個 case_type 有 `firm_base/firm_gap_pct`（全所）與 `office_base/office_gap_pct`（同所別、扣除合署/司法官合署等結構不同）。**比較時優先引用同所別**（更公平），但也要提全所以呈現相對位置。例：「離婚協議書客單價 22,971，同所別基準 30,363（-24%）、全所基準 29,824（-23%）」
4. **必須善用「近一季 vs 更早」的趨勢資料**（`strengths_case_types[*].trend`、`weaknesses_case_types[*].trend`）：
   - **`small_sample=true` 時要謹慎**（近或早 < 3 筆，單筆波動可能是雜訊）。可以提但 why 要明講「樣本小（n=X）需要更多觀察」
   - **「變差」的強項**（樣本不小）→ 這是最緊急的 action（強項正在流失、警訊）。action 的 why 要明講「從 X 元/件掉到 Y 元/件」
   - **「變好」的弱項** → 正面訊號，action 講「延續近期做對的事 + 案件舉例」（可從律師近期案件的 LLM 分析找到做得好的地方）
   - **「近一季無已簽」的強項** → 警訊「案源消失」；「近一季無已簽」的弱項 → 可能是刻意放棄，帶過即可
   - **「變好」的強項**（樣本不小）→ 擴大戰果 action（用什麼做法，怎麼複製到其他案型）
5. **嚴禁通用 SOP 模板**。不要寫「三問 SOP」「48 小時回訪 SOP」這類跨律師都適用的空話，**除非**你能用這位律師 2-3 筆案件的真實記錄證明他就是需要這個
6. **how 至少 3 條具體做法**，每條都要能下次諮詢就開始做；寫具體話術或工具，不寫抽象原則
7. **metric 必須可量化**（%、次數、金額），含目前基線與目標值；**優先用趨勢倒回為目標**（例：「支付命令客單價回到 44K（近一季 15K，半年前 44K）」）
8. **避免重複**：3-4 個 action 要涵蓋不同面向（不要 4 個都是「尾聲話術」）
9. 優先考慮**效益值**與**客單價**，成案率次要（若是因為接高價案使成案率下滑，那是正確策略選擇）

## 輸出（純 JSON，無 markdown 包裝、無前後說明文字）

{{
  "actions": [
    {{
      "title": "簡短標題，不超過 25 字",
      "why": "為何做這件事。必引 1-3 筆具體案件（如：『2026-03-12 李後慶案：律師告知程序後客戶說要回去想，但未當場問顧慮』）。2-5 句",
      "how": ["具體做法 1（可含話術或工具）", "具體做法 2", "具體做法 3", "可選 4"],
      "metric": "下月驗收指標，含『目標值』與『目前基線』",
      "cited_cases": ["2026-03-12 李後慶", "..."]
    }}
  ]
}}
"""

    try:
        client = Anthropic(api_key=api_key, max_retries=10, timeout=180)
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=6000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = resp.content[0].text.strip()
        # 容錯剝掉 ```json 包裝
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().rstrip("`").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as je:
            # JSON 被截斷或有小瑕疵，嘗試救援：往前切到最後一個完整 action + 補尾巴
            recovered = _try_recover_actions_json(text)
            if recovered is None:
                print(f"  [personalized actions] JSON 無法救援 (stop_reason={resp.stop_reason}, "
                      f"out_tokens={resp.usage.output_tokens}): {je}", flush=True)
                raise
            print(f"  [personalized actions] JSON 截斷，救援成功", flush=True)
            data = recovered
        llm_actions = data.get("actions") or []
        if len(llm_actions) < 2:
            print(f"  [personalized actions] LLM 回傳 actions < 2，退回 rule-based", flush=True)
            return rule_based_actions

        normalized = []
        for a in llm_actions:
            normalized.append({
                "title": (a.get("title") or "").strip(),
                "why": (a.get("why") or "").strip(),
                "how": a.get("how") or [],
                "metric": (a.get("metric") or "").strip(),
                "cited_cases": a.get("cited_cases") or [],
            })
        print(f"  [personalized actions] LLM 產出 {len(normalized)} 個 actions "
              f"(in={resp.usage.input_tokens} out={resp.usage.output_tokens})", flush=True)
        return normalized
    except Exception as e:
        print(f"  [personalized actions] 失敗退回 rule-based: {type(e).__name__}: {e}", flush=True)
        return rule_based_actions


def build_html(prep, llm, all_cases=None, lag_stats=None):
    lw = prep["lawyer"]
    ov = prep["overall"]
    rec = prep["recent_agg"]
    prev = prep["prev_agg"]
    delta = prep["period_delta"]
    strengths_types = [s for s in prep.get("strengths", []) if s["case_type"] != "(未指定案件內容)"]
    weaknesses_types = prep.get("weaknesses", [])

    # === 案型趨勢分析：近 6 月 vs 更早 ===
    # 以 prep 的 recent3_months[0] 往前再推 3 個月作為分界
    recent_months = prep.get("recent3_months", [])
    if recent_months:
        yr, mo = recent_months[0].split("-")
        # 近 6 月 = recent3 前 3 月（例：recent3 最早 2026-02 → cutoff 2025-11-01）
        mo_i = int(mo) - 3
        yr_i = int(yr)
        if mo_i <= 0:
            mo_i += 12
            yr_i -= 1
        recent_cutoff = f"{yr_i:04d}-{mo_i:02d}-01"
    else:
        recent_cutoff = "2025-11-01"

    type_trend_rows = []
    trend_narrative = ""
    if all_cases:
        recent_subset, earlier_subset, recent_by_type, earlier_by_type = compute_case_type_trends(all_cases, recent_cutoff)
        # 找最少近 3 筆的案型，比較近/早
        items = []
        for t, d in recent_by_type.items():
            if d["n"] < 3 or t == "(未指定案件內容)":
                continue
            r_rate = d["s"] / d["n"] * 100
            r_unit = d["col"] / d["s"] if d["s"] else 0
            r_eff = d["col"] / d["n"] if d["n"] else 0
            e = earlier_by_type.get(t, {"n": 0, "s": 0, "col": 0})
            e_rate = (e["s"] / e["n"] * 100) if e["n"] else None
            e_unit = (e["col"] / e["s"]) if e["s"] else None
            e_eff = (e["col"] / e["n"]) if e["n"] else None
            items.append({
                "type": t,
                "r_n": d["n"], "r_rate": r_rate, "r_unit": r_unit, "r_eff": r_eff,
                "e_n": e["n"], "e_rate": e_rate, "e_unit": e_unit, "e_eff": e_eff,
                "rate_delta": (r_rate - e_rate) if e_rate is not None else None,
                "unit_delta": (r_unit - e_unit) if (e_unit and r_unit) else None,
                "eff_delta": (r_eff - e_eff) if e_eff is not None else None,
            })
        items.sort(key=lambda x: -x["r_n"])
        type_trend_rows = items[:5]

        # 案型深度分析黃框已移除（提案 B：受登錄偏誤影響，成案率與效益是 artifact）

    unsigned = [c for c in llm if not c["is_signed"]]
    signed = [c for c in llm if c["is_signed"]]

    # case_id → client_name / case_number lookup（prep.json 有但 llm.json 沒有）
    prep_cases = {c["id"]: c for c in prep.get("cases_with_meeting_record", [])}
    def extra(case_id):
        p = prep_cases.get(case_id, {})
        return p.get("client_name"), p.get("case_number")

    # AI 歸因聚合
    reason_counts = Counter(c["analysis"]["failure_reason"] for c in unsigned)
    reason_total = sum(reason_counts.values())
    top_reasons = reason_counts.most_common(5)

    # missed opportunity themes
    all_missed = []
    for c in unsigned:
        all_missed.extend(c["analysis"].get("missed_opportunities") or [])

    def count_theme(keywords):
        return sum(1 for m in all_missed if any(k in m for k in keywords))

    behavior_themes = [
        ("主動報價 / 探預算", ["報價", "費用區間", "預算", "探問預算", "價格"]),
        ("尾聲確認疑慮", ["尾聲", "最後", "確認", "顧慮"]),
        ("強化委任價值", ["價值", "委任必要", "投資報酬", "委任價值", "服務價值"]),
        ("不過早交業務", ["業務", "交給", "客戶經理", "轉交", "轉給"]),
        ("即時蒐證引導", ["蒐證", "證據", "錄音", "當週", "立即"]),
    ]
    behavior_counts = [(name, count_theme(kw)) for name, kw in behavior_themes]
    behavior_counts = [b for b in behavior_counts if b[1] > 0]
    behavior_counts.sort(key=lambda x: -x[1])

    # 強項主題
    strength_themes = pick_top_strength_themes(signed, limit=4)

    # 3 個改進代表案例
    rep_improvements = pick_representative_improvements(unsigned, limit=3)

    # Header 主題 — 依 AI 歸因的失敗原因組合自動判斷
    top2_names = [r for r, _ in top_reasons[:2]]
    top2_cnt = sum(n for _, n in top_reasons[:2])
    top2_pct = top2_cnt / reason_total * 100 if reason_total else 0
    top2_joined = "」+「".join(top2_names) if top2_names else ""

    has_price = any("價格" in r for r in top2_names)
    has_delay = any("延遲" in r or "考慮" in r for r in top2_names)
    has_mismatch = any("需求不符" in r for r in top2_names)
    has_trust = any("信任" in r for r in top2_names)

    if has_price and has_delay:
        focus_title = "報價動線優化 · 拉升客單價"
        theme_sentence = (
            f"這不是諮詢品質問題，而是<b>諮詢到簽約的動線問題</b>"
            f"（律師策略給完 → 直接轉業務 → 客戶回去考慮）。改善這段動線，同時能提升成案率與客單價。"
        )
    elif has_price:
        focus_title = "價格溝通強化"
        theme_sentence = f"核心議題是<b>價格錨定不足</b>：律師未在諮詢現場建立價格共識就轉業務。"
    elif has_delay:
        focus_title = "決策推進 · 縮短遲疑"
        theme_sentence = f"客戶常帶著「回去考慮」離開。核心是<b>諮詢尾聲沒有推客戶下決定</b>。"
    elif has_mismatch:
        focus_title = "案件聚焦 · 過濾方向不符的諮詢"
        theme_sentence = f"核心是<b>客戶需求與事務所擅長範圍的落差</b>，改善篩選或期待管理。"
    elif has_trust:
        focus_title = "專業溝通深化 · 建立信任"
        theme_sentence = f"核心是<b>律師與客戶的信任建立不足</b>。"
    else:
        focus_title = "諮詢表現回顧"
        theme_sentence = ""

    # 決定敘事語氣 — 依據「成案率變動」× 「效益變動」的 2x2 組合
    eff_change = delta.get("consult_eff_delta") or 0
    rate_change = delta.get("sign_rate_delta") or 0

    rate_str = f"<span class='{'up' if rate_change >= 0 else 'down'}'>{rate_change:+.1f}%</span>"
    eff_cls = "down" if eff_change < 0 else "up"
    eff_str = f"<span class='{eff_cls}'>{eff_change:+,.0f}/人</span>"
    base = (
        f"近 3 月成案率從 {fmt_pct(prev['sign_rate'])} 變動到 {fmt_pct(rec['sign_rate'])}（{rate_str}），"
        f"諮詢效益從 {fmt_money(prev['consult_eff'])} 變動到 {fmt_money(rec['consult_eff'])}（{eff_str}）。"
    )

    RATE_THR = 1.0       # % 以內視為持平
    EFF_THR = 1000       # 元/人以內視為持平

    rate_up = rate_change >= RATE_THR
    rate_down = rate_change <= -RATE_THR
    eff_up = eff_change >= EFF_THR
    eff_down = eff_change <= -EFF_THR

    if rate_up and eff_down:
        # 成案率升 + 效益降 — 接更多但每件少（琬琪律師的 pattern）
        verdict = "<b>簡言之：接得到更多案子，但每件收得較少</b>（客單價下滑是主要問題）。"
    elif rate_down and eff_up:
        # 成案率降 + 效益升 — 選擇接高價（策略選擇）
        verdict = "<b>簡言之：選擇接高價案件，成案率下滑但客單價提升</b>——若是刻意的策略選擇，可接受。"
    elif rate_down and eff_down:
        # 兩者都下滑 — 林桑羽的 pattern
        verdict = "<b>簡言之：成案率與客單價同時下滑</b>——不是單純的策略取捨，兩個指標都在弱化，需要找原因。"
    elif rate_up and eff_up:
        # 兩者都上升
        verdict = "<b>簡言之：成案率與客單價同步提升</b>——整體表現變好。"
    else:
        verdict = "<b>簡言之：整體變動不大</b>，屬於月度波動範圍。"

    lead = base + verdict

    # 組 narrative：lead + AI 歸因摘要 + theme_sentence
    if reason_total and top2_joined:
        ai_summary = (
            f"<br><br><b>AI 歸因 {len(unsigned)} 筆未簽案件，{top2_pct:.0f}% 集中在「{top2_joined}」</b>"
            f"——{theme_sentence}"
        )
    else:
        ai_summary = ""
    narrative = lead + ai_summary

    today = datetime.now().strftime("%Y-%m-%d")

    # === 簽約滯後分布（回答「近期案件會不會還沒簽但之後會簽」的疑問）===
    lag_html = ""
    if lag_stats:
        # 判斷右截尾對近期數字的影響大小
        within_30 = lag_stats["within_30"]
        beyond_60 = lag_stats["beyond_60"]
        if within_30 >= 80:
            censor_verdict = (
                f"<b>大部分簽約發生在 30 天內（{within_30:.0f}%）</b>，"
                f"只有 {beyond_60:.0f}% 超過 60 天才簽。"
                f"<b>右截尾偏誤小</b>，近期成案率下滑不能用「之後才會簽」解釋。"
            )
            verdict_cls = "narrative-ok"
        elif within_30 >= 60:
            censor_verdict = (
                f"{within_30:.0f}% 在 30 天內簽約，{beyond_60:.0f}% 超過 60 天。"
                f"<b>近 1 個月的成案率可能被低估 5-10%</b>，但近 3 月整體仍有參考價值。"
            )
            verdict_cls = "narrative-warn"
        else:
            censor_verdict = (
                f"{within_30:.0f}% 在 30 天內簽約，{beyond_60:.0f}% 超過 60 天。"
                f"<b>右截尾偏誤可能較大</b>，近期成案率較不可靠，建議用 60 天前的案件比較。"
            )
            verdict_cls = "narrative-warn"

        lag_html = f"""
        <div class="section" style="page-break-inside: avoid;">
          <div class="section-title">📅 簽約滯後分析（回答「近期未簽不等於不會簽」的疑慮）</div>
          <div class="narrative narrative-sub" style="margin:0;">
            <b>{lag_stats['n_matched']}/{lag_stats['n_signed_total']}</b> 筆已簽案件透過當事人姓名配對收款記錄的首次付款日，估算簽約滯後：
            <br>
            <table class="lag-table">
              <tr>
                <td>中位數</td><td><b>{lag_stats['median']} 天</b></td>
                <td>當天簽</td><td><b>{lag_stats['within_0']:.0f}%</b></td>
                <td>7 天內</td><td><b>{lag_stats['within_7']:.0f}%</b></td>
                <td>30 天內</td><td><b>{lag_stats['within_30']:.0f}%</b></td>
                <td>60 天內</td><td><b>{lag_stats['within_60']:.0f}%</b></td>
                <td>90 天內</td><td><b>{lag_stats['within_90']:.0f}%</b></td>
              </tr>
            </table>
            <br>{censor_verdict}
          </div>
        </div>
        """

    # === 案型趨勢對比表 ===
    trend_table_html = ""
    if type_trend_rows:
        body_rows = []
        for it in type_trend_rows:
            e_unit_s = f"{int(it['e_unit']):,}" if it["e_unit"] else "—"
            ud = it["unit_delta"]
            if ud is None:
                ud_cls, ud_s = "", "—"
            else:
                ud_cls = "down" if ud < 0 else ("up" if ud > 0 else "")
                ud_s = f"{ud/1000:+.0f}千"
            # 件數變動（近 vs 早）
            e_n = it.get("e_n") or 0
            n_delta = it["r_n"] - e_n
            n_cls = "up" if n_delta > 0 else ("down" if n_delta < 0 else "")
            n_delta_s = f"{n_delta:+d}" if n_delta != 0 else "0"
            body_rows.append(
                f"<tr><td><b>{esc(it['type'])}</b></td>"
                f"<td>{it['r_n']}</td>"
                f"<td>{int(it['r_unit']):,}</td>"
                f"<td>{e_n if e_n else '—'}</td>"
                f"<td>{e_unit_s}</td>"
                f"<td class='{n_cls}'>{n_delta_s}</td>"
                f"<td class='{ud_cls}'><b>{ud_s}</b></td>"
                f"</tr>"
            )
        trend_table_html = (
            "<div class='section'>"
            "<div class='section-title'>📊 已成案客單價趨勢：近 6 月 vs 更早</div>"
            "<p class='small' style='margin:0 0 4px;color:#666;'>"
            "※ 因登錄偏誤（未成案幾乎都沒填具體案件內容），這裡<b>只看已成案案件的件數與客單價</b>，不看成案率或效益值。"
            "</p>"
            "<table class='trend-table'><thead><tr>"
            "<th>類型</th><th>近件數</th><th>近客單價</th>"
            "<th>早件數</th><th>早客單價</th>"
            "<th>件數Δ</th><th>客單價Δ</th>"
            "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table></div>"
        )

    # === 已成案客單價 — 強項（高於全所基準）===
    def _fmt_trend(s):
        """近一季 vs 更早的趨勢小字樣（同行顯示）。"""
        t = s.get("trend") or {}
        label = t.get("trend_label") or ""
        small = t.get("small_sample", False)
        r_s = t.get("recent_signed") or 0
        e_s = t.get("earlier_signed") or 0
        r_unit = t.get("recent_avg_collected")
        e_unit = t.get("earlier_avg_collected")
        delta_pct = t.get("unit_delta_pct")
        # 文案與顏色：小樣本時無論變好變差都用 muted（不誤導）
        if small and ("變" in label or "持平" in label):
            cls, arrow = "muted", "⚠"
        elif label.startswith("變好"):
            cls, arrow = "up", "↑"
        elif label.startswith("變差"):
            cls, arrow = "down", "↓"
        elif label == "近一季無已簽":
            cls, arrow = "muted", "○"
        elif label == "新成長案型":
            cls, arrow = "up", "★"
        else:
            cls, arrow = "", "→"
        # 預設 summary：近 X 簽 @ unit / 早 X 簽 @ unit
        r_part = f"{r_s} 簽@{fmt_money(r_unit) if r_unit else '—'}"
        e_part = f"{e_s} 簽@{fmt_money(e_unit) if e_unit else '—'}"
        delta_str = ""
        if delta_pct is not None:
            delta_str = f" {delta_pct:+.0f}%"
        return f"<div class='trend-line'><span class='trend-tag {cls}'>{arrow} {esc(label)}{delta_str}</span> 近一季 {r_part}　｜　更早 {e_part}</div>"

    def _fmt_gap_block(item, is_strength):
        """並列顯示：全所 baseline / 同所別 baseline。"""
        cls = "up" if is_strength else "down"
        sign = "+" if is_strength else ""
        firm_part = (
            f'全所 {fmt_money(item["baseline_avg_collected"])} '
            f'<span class="{cls}">{sign}{item["unit_gap_pct"]:.1f}%</span>'
        )
        if item.get("office_baseline_avg_collected") and item.get("office_unit_gap_pct") is not None:
            office_cls = "up" if item["office_unit_gap_pct"] > 0 else ("down" if item["office_unit_gap_pct"] < 0 else "")
            office_sign = "+" if item["office_unit_gap_pct"] > 0 else ""
            office_part = (
                f' ｜ 同所別 {fmt_money(item["office_baseline_avg_collected"])} '
                f'<span class="{office_cls}">{office_sign}{item["office_unit_gap_pct"]:.1f}%</span>'
                f'（n={item.get("office_baseline_n", 0)}）'
            )
        else:
            office_part = ' ｜ 同所別 <span class="muted">樣本不足</span>'
        return firm_part + office_part

    strength_rows = ""
    for s in strengths_types[:3]:
        strength_rows += (
            f'<li><b>{esc(s["case_type"])}</b> — 已成案客單價 '
            f'<b>{fmt_money(s["my_avg_collected"])}</b>，n={s["my_signed"]} 簽'
            f'<div class="gap-line">{_fmt_gap_block(s, is_strength=True)}</div>'
            f'{_fmt_trend(s)}</li>'
        )

    # === 已成案客單價 — 弱項（低於全所基準）===
    weakness_rows = ""
    for w in weaknesses_types[:3]:
        weakness_rows += (
            f'<li><b>{esc(w["case_type"])}</b> — 已成案客單價 '
            f'<b>{fmt_money(w["my_avg_collected"])}</b>，n={w["my_signed"]} 簽'
            f'<div class="gap-line">{_fmt_gap_block(w, is_strength=False)}</div>'
            f'{_fmt_trend(w)}</li>'
        )

    # === 諮詢型態表現（現場/視訊/電話）===
    method_rows = ""
    for cm in prep.get("consult_method_stats", []):
        rate_g = cm.get("sign_rate_gap")
        eff_g = cm.get("eff_gap")
        rate_cls = "up" if (rate_g or 0) > 0 else ("down" if (rate_g or 0) < 0 else "")
        eff_cls = "up" if (eff_g or 0) > 0 else ("down" if (eff_g or 0) < 0 else "")
        rate_s = f"<span class='{rate_cls}'>{rate_g:+.1f}%</span>" if rate_g is not None else "—"
        eff_s = f"<span class='{eff_cls}'>{int(eff_g):+,}</span>" if eff_g is not None else "—"
        method_rows += (
            f"<tr>"
            f"<td><b>{esc(cm['method'])}</b></td>"
            f"<td>{cm['n']}</td>"
            f"<td>{fmt_pct(cm['my_sign_rate'])}</td>"
            f"<td>{fmt_pct(cm.get('baseline_sign_rate'))}</td>"
            f"<td>{rate_s}</td>"
            f"<td>{fmt_money(cm['my_consult_eff'])}</td>"
            f"<td>{fmt_money(cm.get('baseline_consult_eff'))}</td>"
            f"<td>{eff_s}</td>"
            f"</tr>"
        )
    method_table_html = ""
    if method_rows:
        # 統計範圍說明：prep.consult_method_stats 是全部歷史，不是近 3 月
        total_overall = sum(cm["n"] for cm in prep.get("consult_method_stats", []))
        method_table_html = f"""
        <div class="section">
          <div class="section-title">📞 諮詢型態長期表現（全部 {total_overall} 筆歷史案件 vs 全所基準）</div>
          <p class="small" style="margin:0 0 4px;color:#666;">
            這是「如何諮詢」的維度（與上方「案件內容」不同）— <b>統計範圍：律師全部歷史案件</b>，和上方「近 3 月拆解」的數字不同（近 3 月樣本小、本表看長期平均 vs 全所基準）。
          </p>
          <table class="method-table">
            <thead><tr>
              <th>型態</th><th>n</th><th>你成案率</th><th>基準</th><th>差距</th>
              <th>你客單價</th><th>基準</th><th>差距</th>
            </tr></thead>
            <tbody>{method_rows}</tbody>
          </table>
        </div>
        """

    # === 近 3 月成案率拆解（兩個維度）— 解釋分類偏誤 ===
    recent_breakdown_html = ""
    if all_cases and prep.get("recent3_months"):
        recent_cutoff_3m = prep["recent3_months"][0] + "-01"
        recent3_cases = [c for c in all_cases if c.get("case_date") and c["case_date"] >= recent_cutoff_3m]
        total_recent = len(recent3_cases)
        signed_recent = sum(1 for c in recent3_cases if c.get("is_signed"))

        if total_recent > 0:
            # 按案件內容
            by_content = {}
            for c in recent3_cases:
                k = clean_case_type(c.get("case_type"))
                d = by_content.setdefault(k, {"n": 0, "s": 0, "col": 0})
                d["n"] += 1
                if c.get("is_signed"): d["s"] += 1
                d["col"] += c.get("collected") or 0
            # 按諮詢型態
            by_method = {}
            for c in recent3_cases:
                k = extract_consult_method(c.get("case_type"))
                d = by_method.setdefault(k, {"n": 0, "s": 0, "col": 0})
                d["n"] += 1
                if c.get("is_signed"): d["s"] += 1
                d["col"] += c.get("collected") or 0

            def make_rows(grouped, order_by="n"):
                items = sorted(grouped.items(), key=lambda kv: -kv[1]["n"])
                rows = ""
                for k, d in items:
                    rate = d["s"] / d["n"] * 100 if d["n"] else 0
                    # 未指定的那列標紅色強調
                    is_unspec = k in ("(未指定案件內容)", "(未標記)")
                    rate_cls = "down" if is_unspec and rate < 10 else ("up" if rate >= 70 else "")
                    rows += (
                        f"<tr{' class=unspec-row' if is_unspec else ''}>"
                        f"<td>{esc(k)}</td>"
                        f"<td>{d['n']}</td>"
                        f"<td>{d['s']}</td>"
                        f"<td><span class='{rate_cls}'>{rate:.0f}%</span></td>"
                        f"<td class='right'>{fmt_money(d['col'])}</td>"
                        f"</tr>"
                    )
                return rows

            content_rows = make_rows(by_content)
            method_rows_b = make_rows(by_method)

            # 找最大的「未指定/未標記」類別作為偏誤說明依據
            unspec_content = by_content.get("(未指定案件內容)", {"n": 0, "s": 0})
            caveat = ""
            if unspec_content["n"] >= 5:
                non_unspec_n = total_recent - unspec_content["n"]
                non_unspec_s = signed_recent - unspec_content["s"]
                non_rate = non_unspec_s / non_unspec_n * 100 if non_unspec_n else 0
                unspec_rate = unspec_content["s"] / unspec_content["n"] * 100 if unspec_content["n"] else 0
                caveat = (
                    f"<div class='caveat-box'>"
                    f"<b>⚠️ 統計偏誤提醒：</b>近 3 月 <b>{total_recent}</b> 筆案件中，"
                    f"<b>「未指定案件內容」{unspec_content['n']} 筆成案率 {unspec_rate:.0f}%</b>"
                    f"（律師通常只對已成案案件補填具體案件內容 → 未指定 ≈ 未成案的近似指標），"
                    f"其餘 <b>{non_unspec_n} 筆有具體案件內容的成案率 {non_rate:.0f}%</b>。"
                    f"<br><b>因此本 PDF 的「已成案客單價」區塊只看已成案案件（不算成案率）</b>，"
                    f"因為未成案諮詢幾乎都被歸到未指定，不會進入支付命令/民事一審等具體類別的分母——"
                    f"用成案率比較會是 artifact。"
                    f"<br>建議律師把『未成案諮詢』也補填案件內容欄位（例如『支付命令（未成案）』），"
                    f"才能讓各案型的成案率反映真實拒絕比例。"
                    f"</div>"
                )

            recent_breakdown_html = f"""
            <div class="section" style="page-break-inside: avoid;">
              <div class="section-title">📊 近 3 月成案率拆解 · 僅 {total_recent} 筆近期案件（整體 {signed_recent}/{total_recent} = {signed_recent/total_recent*100:.1f}%）</div>
              <div class="two-col">
                <div>
                  <div class="sub-title">按案件內容</div>
                  <table class="breakdown-table">
                    <thead><tr><th>類別</th><th>n</th><th>簽</th><th>率</th><th>收款</th></tr></thead>
                    <tbody>{content_rows}</tbody>
                  </table>
                </div>
                <div>
                  <div class="sub-title">按諮詢型態</div>
                  <table class="breakdown-table">
                    <thead><tr><th>類別</th><th>n</th><th>簽</th><th>率</th><th>收款</th></tr></thead>
                    <tbody>{method_rows_b}</tbody>
                  </table>
                </div>
              </div>
              {caveat}
            </div>
            """

    # === 月度趨勢表（揭示轉折點，避免「近 3 月」被誤解為均勻下滑）===
    monthly_trend_html = ""
    monthly = prep.get("monthly_trend", [])
    if monthly:
        # 取最近 12 個月
        last12 = monthly[-12:]
        # 先掃近 6 個月找「結構性轉折點」：跌幅 >= 30% + 前月 >= 20K + 後續月份沒回到前月水準
        turning_month = None
        turning_drop_pct = 0
        # 只看近 6 月（保留舊歷史資料但不當轉折點候選 — 避免 2025-07 淡季單月雜訊）
        scope_len = min(6, len(last12))
        scope = last12[-scope_len:]
        scope_effs = [(m.get("collected") or 0) / m.get("consult_count") if m.get("consult_count") else 0 for m in scope]
        for i in range(1, len(scope)):
            prev = scope_effs[i - 1]
            cur = scope_effs[i]
            if prev < 20000 or cur <= 0:
                continue
            drop = (prev - cur) / prev
            if drop < 0.30:
                continue
            # 結構性檢查：後續月份有沒有回到 prev 的 80% 水準？沒回到才算結構性
            later = scope_effs[i + 1:]
            recovered = any(e >= prev * 0.8 for e in later) if later else False
            if recovered:
                continue
            # 選**最新**的轉折點（覆蓋舊的）
            turning_month = scope[i]["month"]
            turning_drop_pct = drop

        rows_m = []
        for idx, m in enumerate(last12):
            n_c = m.get("consult_count") or 0
            n_s = m.get("signed_count") or 0
            col = m.get("collected") or 0
            rate = m.get("sign_rate") or 0
            eff = col / n_c if n_c else 0

            is_turning = (m["month"] == turning_month)
            row_class = ' style="background:#fee2e2;"' if is_turning else ""
            rate_color = "up" if rate >= 50 else ("down" if rate < 30 else "")
            rows_m.append(
                f"<tr{row_class}>"
                f"<td><b>{esc(m['month'])}</b></td>"
                f"<td>{n_c}</td>"
                f"<td>{n_s}</td>"
                f"<td class='{rate_color}'>{rate:.0f}%</td>"
                f"<td>{int(col):,}</td>"
                f"<td><b>{int(eff):,}</b></td>"
                f"</tr>"
            )

        # 組 narrative（如有明顯轉折點）
        turning_note = ""
        if turning_month:
            turning_note = (
                f'<p class="small" style="margin:4px 0 0;color:#b91c1c;">'
                f'⚠️ <b>{turning_month} 是效益下滑的轉折點</b>（效益較前月下滑 {turning_drop_pct*100:.0f}%）'
                f'—— 會議中可以問律師「{turning_month} 有什麼不一樣嗎？」'
                f'這比「近 3 月整體下滑」的 framing 更精準。'
                f'</p>'
            )

        monthly_trend_html = f"""
        <div class="section" style="page-break-inside: avoid;">
          <div class="section-title">📅 近 12 個月月度趨勢（揭示轉折點，對照儀表板的 YTD 數字）</div>
          <p class="small" style="margin:0 0 4px;color:#666;">
            ※ <b>為什麼這份 PDF 跟事務所儀表板的數字看起來不同？</b>
            儀表板通常是「本年度 YTD」（含 1 月至當月）；本 PDF 的「近 3 月」是 rolling 最近三個月，不一定包含 1 月。
            <b>真正的下滑訊號藏在月度趨勢裡</b>——不要只看 3 個月平均。
          </p>
          <table class="month-trend-table">
            <thead><tr>
              <th>月份</th><th>諮詢</th><th>簽</th><th>成案率</th><th>收款</th><th>效益/人</th>
            </tr></thead>
            <tbody>{''.join(rows_m)}</tbody>
          </table>
          {turning_note}
        </div>
        """

    # === 資料補填漏洞：已成案但案件內容欄位未補填 ===
    # 這 section 只關注「已簽約但 case_type 只填諮詢方式」的漏洞
    # 未成案的未指定案件大部分是諮詢費 2,000 的失敗案件，細節討論價值低
    # （失敗模式已被 AI 歸因 section 覆蓋）
    unspecified_html = ""
    if all_cases:
        def is_unspecified(c):
            t = c.get("case_type")
            if not t or not t.strip():
                return True
            parts = [p.strip() for p in re.split(r"[,，、]", t) if p.strip()]
            return all(p in CONSULT_METHODS for p in parts)

        # 只挑「已簽約 + 案件內容未補填」的案件
        gap_cases = [c for c in all_cases if c.get("is_signed") and is_unspecified(c)]
        # 日期新的排前面
        gap_cases.sort(key=lambda c: c.get("case_date") or "", reverse=True)

        if gap_cases:
            rows = []
            for c in gap_cases:
                raw_type = (c.get("case_type") or "").strip() or "(空白)"
                client = c.get("client_name") or "—"
                case_no = c.get("case_number") or ""
                collected = c.get("collected") or 0
                note = ""
                if (c.get("lawyer_notes") or "").strip():
                    note = (c["lawyer_notes"].strip()[:50]).replace("\n", " ")
                elif (c.get("tracking_notes") or "").strip():
                    note = (c["tracking_notes"].strip()[:50]).replace("\n", " ")

                rows.append(
                    f"<tr>"
                    f"<td>{c.get('case_date') or '—'}</td>"
                    f"<td><b>{esc(client)}</b></td>"
                    f"<td class='small'>{esc(case_no)}</td>"
                    f"<td class='small'>{esc(raw_type)}</td>"
                    f"<td class='right'>{fmt_money(collected) if collected else '—'}</td>"
                    f"<td class='small'>{esc(note)}</td>"
                    f"</tr>"
                )

            unspecified_html = f"""
        <div class="section" style="page-break-inside: avoid;">
          <div class="section-title">⚠️ 資料補填漏洞：{len(gap_cases)} 筆已簽約案件 case_type 欄位只填了諮詢方式</div>
          <div class="narrative narrative-sub" style="margin:0 0 6px;padding:6px 10px;">
            這些案件<b>已成案收到委任費</b>，但 case_type 欄位只記錄「現場諮詢/視訊諮詢/電話諮詢」，沒寫具體案件內容（例如支付命令、民事一審）。
            <b>建議律師回去把案件內容補上</b>，這樣下次產備忘單時「已成案客單價」統計會更精準（且有利於事務所其他分析）。
          </div>
          <table class="unspec-table">
            <thead><tr>
              <th>日期</th><th>當事人</th><th>案號</th><th>原欄位填寫</th><th>收款</th><th>現有備註</th>
            </tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table>
        </div>
        """

    # === 強項主題卡片 ===
    strength_cards = ""
    for t in strength_themes:
        case = t["example"]["case"]
        text = t["example"]["text"]
        client, case_no = extra(case["case_id"])
        client_part = f"當事人 <b>{esc(client)}</b> · " if client else ""
        case_no_part = f"案號 {esc(case_no)} · " if case_no else ""
        case_label = f"{case['case_date']} · {client_part}{esc(case['case_type'] or '')} · {case_no_part}成交 {fmt_money(case.get('collected'))}"
        strength_cards += f'''
        <div class="s-card">
          <div class="s-card-title">✓ {esc(t["name"])} <span class="s-card-count">（{t["count"]} 筆案件出現）</span></div>
          <div class="s-quote">「{esc(text)}」</div>
          <div class="s-meta">案例：{case_label}</div>
        </div>
        '''

    # === 失敗原因 bar ===
    reason_rows = ""
    for r, n in top_reasons:
        pct = n / reason_total * 100 if reason_total else 0
        reason_rows += f'''
        <div class="reason-row">
          <div class="reason-label">{esc(r)}</div>
          <div class="reason-bar-wrap">
            <div class="reason-bar" style="width:{pct:.1f}%"></div>
            <span class="reason-count">{n} 筆（{pct:.0f}%）</span>
          </div>
        </div>
        '''

    # === 行為斷點 bar ===
    max_b = max((c for _, c in behavior_counts), default=1)
    theme_rows = ""
    for name, cnt in behavior_counts:
        pct = cnt / max_b * 100
        theme_rows += f'''
        <div class="theme-row">
          <div class="theme-label">{esc(name)}</div>
          <div class="theme-bar-wrap">
            <div class="theme-bar" style="width:{pct:.0f}%"></div>
            <span class="theme-count">{cnt} 次</span>
          </div>
        </div>
        '''

    # === 3 個改進建議（詳細卡片）===
    improvement_cards = ""
    for i, case in enumerate(rep_improvements, 1):
        a = case["analysis"]
        reason = a.get("failure_reason", "")
        evidence = a.get("reason_evidence", "")
        missed_list = a.get("missed_opportunities") or []
        improvement = a.get("improvement_for_lawyer", "")
        pattern = a.get("transferable_pattern", "")

        missed_html = ""
        if missed_list:
            missed_html = "<ul class='missed'>" + "".join(f"<li>{esc(m)}</li>" for m in missed_list[:3]) + "</ul>"

        # 收款為 0 的未簽案件不顯示金額
        collected_str = f"收款 ${fmt_money(case.get('collected'))}" if case.get("collected") else "未簽（諮詢費 $0 或未收）"
        client, case_no = extra(case["case_id"])
        client_part = f"當事人 <b>{esc(client)}</b> · " if client else ""
        case_no_part = f"案號 {esc(case_no)} · " if case_no else ""

        improvement_cards += f'''
        <div class="imp-card">
          <div class="imp-head">
            <span class="imp-num">#{i}</span>
            <span class="imp-title">{esc(reason)}</span>
            <span class="imp-meta">{case["case_date"]} · {client_part}{esc(case.get("case_type") or "")} · {case_no_part}{collected_str}</span>
          </div>

          <div class="imp-sub">📖 從會議記錄看出來的原文證據</div>
          <div class="imp-quote">「{esc(evidence)}」</div>

          <div class="imp-sub">⚠️ 律師錯過的動作</div>
          {missed_html}

          <div class="imp-sub">💡 AI 建議下次怎麼做</div>
          <div class="imp-body">{esc(improvement)}</div>

          {f'<div class="imp-pattern"><b>可類推模式：</b>{esc(pattern)}</div>' if pattern else ""}
        </div>
        '''

    # === 會議討論 Q ===
    questions = [
        "策略給完後，通常怎麼收尾？會主動問客戶預算或決策時間嗎？",
        "什麼情況下你會當場給報價區間、什麼情況直接交給業務？過去有成功案例嗎？",
    ]
    # 若有主力案型下滑 — 須樣本 >= 10 且成案率下滑 >= 10pp（避免小樣本雜訊）
    if all_cases and type_trend_rows:
        top = type_trend_rows[0]
        if (top.get("rate_delta") or 0) <= -10 and top["r_n"] >= 10:
            questions.append(
                f"你主力做「{top['type']}」案件（近 6 月 {top['r_n']} 筆佔 {top['r_n']/len(recent_subset)*100:.0f}%），"
                f"成案率從 {top['e_rate']:.0f}% 掉到 {top['r_rate']:.0f}%，印象中最近這類案件遇到的客戶類型、案件性質有沒有改變？"
            )
        # 若有案型諮詢效益明顯下滑 — 須同時滿足：絕對變動 >= 10,000、相對變動 >= 15%、樣本 >= 5
        big_eff_drop = []
        for it in type_trend_rows:
            ed = it.get("eff_delta") or 0
            e_eff = it.get("e_eff") or 0
            if ed <= -10000 and e_eff > 0 and abs(ed) / e_eff >= 0.15 and it["r_n"] >= 5:
                big_eff_drop.append(it)
        if big_eff_drop:
            it = big_eff_drop[0]
            drop_pct = abs(it["eff_delta"]) / it["e_eff"] * 100
            questions.append(
                f"「{it['type']}」近 6 月效益值從 {int(it['e_eff']):,}/人 掉到 {int(it['r_eff']):,}/人"
                f"（跌 {drop_pct:.0f}%，{it['r_n']} 筆）——是接到比較單純/低價的案件嗎？還是報價時折讓？"
            )

    # 弱項案型提問 — 須已成案 >= 10 筆 且客單價顯著低於全所基準（>= 15%）
    if weaknesses_types:
        significant_weak = None
        for w in weaknesses_types:
            if w["my_signed"] < 10:
                continue
            gap_pct = abs(w["unit_gap_pct"])
            if gap_pct >= 15:
                significant_weak = (w, gap_pct)
                break
        if significant_weak:
            w, magnitude = significant_weak
            questions.append(
                f"「{w['case_type']}」已成案 {w['my_signed']} 筆，你的客單價 {fmt_money(w['my_avg_collected'])} "
                f"比全所基準 {fmt_money(w['baseline_avg_collected'])} 低 {magnitude:.0f}%——"
                f"是接的案情比較單純、還是報價時有折讓空間可以優化？"
            )
    questions_html = "".join(f"<li>{esc(q)}</li>" for q in questions)

    # === 後續行動重點（根據資料自動生成 3-4 項）===
    # 近 3 月已簽客單價（用於 cross-sell action 的動態目標）
    rec_unit = (rec.get("collected") / rec["signed_count"]) if rec.get("signed_count") else 0

    # 先建 rule-based actions 作為 LLM 失敗時的 fallback
    rule_based_actions = []
    actions = rule_based_actions  # 先指到同一個 list，之後如果 LLM 成功會替換

    # Action 1：最高頻行為斷點 → SOP
    if behavior_counts:
        top_b_name, top_b_cnt = behavior_counts[0]
        # 合併前兩高的斷點做成一個 SOP
        has_end = any("尾聲" in n for n, _ in behavior_counts[:3])
        has_price = any("報價" in n or "預算" in n for n, _ in behavior_counts[:3])
        if has_price and has_end:
            actions.append({
                "title": "諮詢結尾「三問」標準流程（轉業務前必問）",
                "why": (
                    f"{len(unsigned)} 筆未簽案件中 {top2_pct:.0f}% 集中在「{top2_joined}」。"
                    f"AI 在會議記錄裡抓到「{behavior_counts[0][0]}」錯過 {behavior_counts[0][1]} 次，是最高頻的漏洞。"
                ),
                "how": [
                    "Q1：「您這邊大概什麼時候會做決定？」",
                    "Q2：「費用這塊有沒有需要我先讓您了解的範圍？」",
                    "Q3：「今天討論下來，還有什麼顧慮嗎？」",
                    "規則：沒問完 3 題前不轉客戶經理。",
                ],
                "metric": f"下次 AI 分析：「{behavior_counts[0][0]}」斷點 < {max(3, int(behavior_counts[0][1] * 0.5))} 次（目前 {behavior_counts[0][1]} 次）",
            })
        else:
            actions.append({
                "title": f"優先改善「{top_b_name}」",
                "why": f"AI 歸因顯示「{top_b_name}」在 17 筆未簽案件中出現 {top_b_cnt} 次，是你最高頻漏掉的動作。",
                "how": ["每次諮詢後自檢：這次有沒有做到這個動作？沒有的話下次怎麼補？"],
                "metric": f"下次 AI 分析：「{top_b_name}」斷點 < {int(top_b_cnt*0.5)} 次",
            })

    # Action 2：當場報價 + ROI 框架（洪琬琪的 #1 改進案例就是這個）
    if reason_counts.get("價格疑慮", 0) >= 3:
        actions.append({
            "title": "當場報價區間 + 投資報酬率論述",
            "why": f"「價格疑慮」佔未簽案件 {reason_counts.get('價格疑慮', 0)}/{reason_total} 筆（{reason_counts.get('價格疑慮', 0)/reason_total*100:.0f}%）。客戶當場問費用時，律師轉給業務 = 客戶帶著「不確定」離開。",
            "how": [
                "客戶第 2 次問費用時，給個區間（即使最後由業務報正式價）",
                "對可量化案件（車禍/債權/家事）：用「爭取金額 vs 律師費」的投資報酬率框架說服",
                "不符法扶時：主動提「僅委任 X 階段」的低門檻方案",
            ],
            "metric": f"「價格疑慮」未簽占比 < {int(reason_counts.get('價格疑慮', 0)/reason_total*100*0.65)}%（目前 {reason_counts.get('價格疑慮', 0)/reason_total*100:.0f}%）",
        })

    # Action 3：決策延遲客戶的 48h 回訪 SOP（只要「客戶決策延遲」>=3 筆就加）
    delay_cnt = reason_counts.get("客戶決策延遲（回去考慮、跟家人討論）", 0)
    if delay_cnt >= 3 and lag_stats:
        actions.append({
            "title": "「回去考慮」客戶的 48 小時回訪標準流程",
            "why": (
                f"未簽案件中有 {delay_cnt} 筆「客戶決策延遲」（佔 {delay_cnt/reason_total*100:.0f}%），"
                f"這些客戶當下沒表達拒絕但沒簽。同時簽約滯後分析顯示 <b>{lag_stats['within_7']:.0f}% 在 7 天內簽、{lag_stats['within_30']:.0f}% 在 30 天內</b>，"
                f"過了這個窗口基本就失聯。<b>回訪機會窗口很短，但值得搶</b>。"
            ),
            "how": [
                "諮詢結束後 48 小時內律師本人發 LINE 訊息：「我回去想了一下您的案件，附上 OO 判決/資料供參考」",
                "給業務一份「回訪名單」：諮詢後 3 天沒簽 → 業務主動問「您有什麼疑問嗎？」",
                "把客戶具體擔心的點（諮詢當下聽到的）做成後續溝通的切入點，不要制式客套",
            ],
            "metric": f"下月「客戶決策延遲」未簽占比 < {max(20, int(delay_cnt/reason_total*100*0.6))}%（目前 {delay_cnt/reason_total*100:.0f}%）",
        })

    # Action 4：已簽案件 延伸業務 / 深掘（拉客單價不靠犧牲成案率）
    # 條件：有一定簽案量，且強項包含「策略」「法律依據」等（表示她能辨識更多需求）
    if len(signed) >= 10:
        actions.append({
            "title": "已簽案件的 延伸業務探索（拉客單價無上限）",
            "why": (
                f"整體客單價 {int(ov['avg_collected']):,} 尚可，但家事/民事案件常有<b>連鎖需求</b>"
                "（離婚 → 財產分配 → 監護探視 → 遺產）。"
                "律師在提供完整策略時，常聚焦「眼前這件」，沒主動探索客戶是否還有其他法律事務。"
            ),
            "how": [
                "諮詢結尾補一句：「除了這件之外，您目前有沒有其他法律上的困擾？工作、投資、家人？」",
                "簽約後補問：「這個案件結束之前，如果有其他需要提醒的事情（例如更新遺囑、公司股東協議），也可以先跟我講」",
                "針對高客單案型（家事一審、刑事偵查）：預先準備「延伸服務」清單，諮詢中對應提出",
            ],
            "metric": f"下月已簽案件平均客單價 ≥ {int(rec_unit * 1.15):,}（近 3 月 {int(rec_unit):,}）",
        })

    # === 嘗試用 LLM 產個人化 actions（失敗時用上面的 rule_based_actions）===
    actions = generate_personalized_actions(
        lw=lw, prep=prep, llm=llm, unsigned=unsigned, signed=signed,
        reason_counts=reason_counts, reason_total=reason_total,
        behavior_counts=behavior_counts, lag_stats=lag_stats,
        rec=rec, ov=ov, extra_fn=extra,
        strengths_types=strengths_types, weaknesses_types=weaknesses_types,
        rule_based_actions=rule_based_actions,
    )

    # 組 actions HTML
    action_cards = ""
    for i, a in enumerate(actions, 1):
        how_html = "<ul class='act-how'>" + "".join(f"<li>{esc(h)}</li>" for h in a["how"]) + "</ul>"
        cited_html = ""
        if a.get("cited_cases"):
            cited_list = "、".join(esc(c) for c in a["cited_cases"][:4])
            cited_html = f'<div class="act-cited"><b>引用案件：</b>{cited_list}</div>'
        action_cards += f"""
        <div class="act-card">
          <div class="act-head">
            <span class="act-num">#{i}</span>
            <span class="act-title">{esc(a['title'])}</span>
          </div>
          {cited_html}
          <div class="act-why"><b>為什麼：</b>{a['why']}</div>
          <div class="act-sub">具體做法：</div>
          {how_html}
          <div class="act-metric"><b>📊 下月驗收指標：</b>{esc(a['metric'])}</div>
        </div>
        """

    # 追蹤機制（動態：根據律師實際 actions、行為斷點、指標生成）
    today_dt = datetime.now()
    from datetime import timedelta
    next_1on1 = (today_dt + timedelta(days=28)).strftime("%Y-%m-%d")
    mid_review = (today_dt + timedelta(days=14)).strftime("%Y-%m-%d")

    # 每週自檢：引用 action #1 的核心動作（若無 action，用泛用文案）
    if actions:
        weekly_check = f"每週結束前回想 — 本週諮詢是否落實「{esc(actions[0]['title'])}」？哪幾筆忘了？"
    else:
        weekly_check = "每週結束前回想本週諮詢有哪些可以改進的動作"

    # 期中回顧：追蹤最高頻的行為斷點
    if behavior_counts:
        top_b_name, top_b_cnt = behavior_counts[0]
        mid_check = f"跑一次 AI 分析最新一週諮詢記錄，看「{esc(top_b_name)}」斷點次數有無下降（目前 {top_b_cnt} 次）"
    else:
        mid_check = "跑一次 AI 分析最新一週諮詢記錄，看行為斷點整體是否改善"

    # 下次 1-on-1：動態計算指標（基於這位律師近 3 月實際數字）
    cur_eff = rec.get('consult_eff') or 0
    target_eff = int(cur_eff * 1.15 / 1000) * 1000 if cur_eff else 30000
    rec_avg_unit = (rec['collected'] / rec['signed_count']) if rec.get('signed_count') else 0
    target_unit = int(rec_avg_unit * 1.15 / 1000) * 1000 if rec_avg_unit else 60000

    # 最高佔比的前 2 個失敗原因（去掉「已簽約」）
    top2 = [(r, n) for r, n in top_reasons if r != "已簽約"][:2]
    top2_total = sum(n for _, n in top2)
    top2_pct = (top2_total / reason_total * 100) if reason_total else 0
    top2_names = "＋".join(f"「{r}」" for r, _ in top2) if top2 else "主要失敗原因"
    target_top2 = max(20, int(top2_pct * 0.65))

    # 行為斷點目標
    behavior_line = ""
    if behavior_counts:
        bn, bc = behavior_counts[0]
        behavior_line = f'<li>AI 行為斷點「{esc(bn)}」：目標 &lt; {max(1, int(bc*0.5))} 次（目前 {bc} 次）</li>'

    indicators_html = f"""
            <li><b>整體諮詢效益</b>：目標 ≥ {target_eff:,}/人（近3月 {int(cur_eff):,}）← <b>首要指標</b></li>
            <li><b>已簽案件平均客單價</b>：目標 ≥ {target_unit:,}（近3月 {int(rec_avg_unit):,}）← 延伸業務探索效果</li>
            <li>未簽失敗原因{top2_names} 合計占比：目標 &lt; {target_top2}%（目前 {top2_pct:.0f}%）</li>
            {behavior_line}
    """

    tracking_html = f"""
    <div class="track-box">
      <ol class="track-list" style="margin-top:0;">
        <li><b>每週自檢</b>（律師自己）：{weekly_check}</li>
        <li><b>期中回顧（{mid_review}）</b>：{mid_check}。這是<b>行為指標</b>，不用等月結。</li>
        <li><b>下次 1-on-1（約 {next_1on1}）</b>：重跑完整備忘單，對比關鍵指標（<b>以效益值為王，成案率次要</b>）：
          <ul style="margin-top:3px;">
            {indicators_html}
          </ul>
        </li>
      </ol>
    </div>
    """

    # === HTML ===
    html_out = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<title>{esc(lw['name'])} 1-on-1 備忘單</title>
<style>
  @page {{ size: A4; margin: 12mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "PingFang TC", "Microsoft JhengHei", "Noto Sans TC", sans-serif;
    color: #1a1a1a;
    font-size: 10.5pt;
    line-height: 1.55;
    margin: 0;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  h1, h2, h3 {{ margin: 0; font-weight: 600; }}
  b {{ font-weight: 600; }}
  .up {{ color: #15803d; font-weight: 600; }}
  .down {{ color: #b91c1c; font-weight: 600; }}
  .muted {{ color: #64748b; font-weight: 600; }}
  .trend-line {{
    font-size: 9pt;
    color: #475569;
    margin: 3px 0 2px 0;
    padding-left: 4px;
  }}
  .gap-line {{
    font-size: 9pt;
    color: #334155;
    margin: 2px 0 2px 0;
    padding-left: 4px;
  }}
  .trend-tag {{
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    background: #f1f5f9;
    margin-right: 6px;
    font-size: 8.5pt;
  }}
  .trend-tag.up {{ background: #dcfce7; color: #15803d; }}
  .trend-tag.down {{ background: #fee2e2; color: #b91c1c; }}
  .trend-tag.muted {{ background: #e2e8f0; color: #475569; }}
  .small {{ font-size: 9pt; color: #555; }}

  .page-container {{ max-width: 182mm; margin: 0 auto; }}

  /* Header */
  .hdr {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2.5px solid #1e3a8a;
    padding-bottom: 8px;
    margin-bottom: 12px;
  }}
  .hdr-title {{ font-size: 19pt; font-weight: 700; color: #1e3a8a; }}
  .hdr-sub {{ font-size: 10pt; color: #555; margin-top: 3px; }}
  .hdr-meta {{ text-align: right; font-size: 9.5pt; color: #555; line-height: 1.6; }}
  .focus-tag {{
    display: inline-block;
    background: #fef3c7;
    color: #92400e;
    font-size: 10pt;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 4px;
    margin-top: 6px;
  }}

  /* Narrative */
  .narrative {{
    background: #f8fafc;
    border-left: 3px solid #1e3a8a;
    padding: 10px 14px;
    font-size: 10.5pt;
    margin-bottom: 14px;
  }}
  .narrative-sub {{
    background: #fef9c3;
    border-left: 3px solid #ca8a04;
  }}

  /* Trend table */
  .trend-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
    margin-top: 2px;
  }}
  .trend-table th, .trend-table td {{
    padding: 4px 6px;
    border: 1px solid #e5e7eb;
    text-align: right;
  }}
  .trend-table th {{
    background: #eff6ff;
    font-weight: 600;
    color: #1e3a8a;
  }}
  .trend-table th:first-child, .trend-table td:first-child {{
    text-align: left;
  }}
  .trend-table tbody tr:nth-child(even) {{ background: #fafbfc; }}

  /* Lag table */
  .lag-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 4px 0;
    font-size: 9.5pt;
  }}
  .lag-table td {{
    padding: 3px 6px;
    border: 1px solid #e5e7eb;
    text-align: center;
    background: #fff;
  }}
  .lag-table td:nth-child(odd) {{
    background: #f8fafc;
    color: #555;
    font-size: 8.5pt;
  }}

  /* Unspecified case type table */
  .unspec-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9pt;
    margin-top: 4px;
  }}
  .unspec-table th, .unspec-table td {{
    padding: 4px 6px;
    border: 1px solid #e5e7eb;
    text-align: left;
    vertical-align: top;
  }}
  .unspec-table th {{
    background: #fef3c7;
    font-weight: 600;
    color: #92400e;
  }}
  .unspec-table tbody tr:nth-child(even) {{ background: #fafbfc; }}
  .unspec-table td.right {{ text-align: right; }}

  /* Monthly trend table */
  .month-trend-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
    margin-top: 4px;
  }}
  .month-trend-table th, .month-trend-table td {{
    padding: 4px 8px;
    border: 1px solid #e5e7eb;
    text-align: right;
  }}
  .month-trend-table th {{
    background: #e0e7ff;
    font-weight: 600;
    color: #3730a3;
  }}
  .month-trend-table th:first-child,
  .month-trend-table td:first-child {{ text-align: left; }}
  .month-trend-table tbody tr:nth-child(even) {{ background: #fafbfc; }}

  /* Recent breakdown tables */
  .breakdown-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
  }}
  .breakdown-table th, .breakdown-table td {{
    padding: 3px 6px;
    border: 1px solid #e5e7eb;
    text-align: right;
  }}
  .breakdown-table th {{
    background: #ede9fe;
    color: #5b21b6;
    font-weight: 600;
  }}
  .breakdown-table th:first-child, .breakdown-table td:first-child {{ text-align: left; }}
  .breakdown-table td.right {{ text-align: right; }}
  .breakdown-table tr.unspec-row td {{ background: #fef3c7; }}
  .sub-title {{
    font-size: 10pt;
    font-weight: 600;
    color: #5b21b6;
    margin-bottom: 3px;
  }}
  .caveat-box {{
    background: #fffbeb;
    border: 1px solid #fcd34d;
    border-left: 3px solid #d97706;
    border-radius: 4px;
    padding: 8px 12px;
    margin-top: 8px;
    font-size: 9.5pt;
    line-height: 1.55;
  }}

  /* Consult method table */
  .method-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
    margin-top: 2px;
  }}
  .method-table th, .method-table td {{
    padding: 4px 6px;
    border: 1px solid #e5e7eb;
    text-align: right;
  }}
  .method-table th {{
    background: #e0f2fe;
    font-weight: 600;
    color: #0369a1;
  }}
  .method-table th:first-child, .method-table td:first-child {{ text-align: left; }}
  .method-table tbody tr:nth-child(even) {{ background: #fafbfc; }}

  /* Metric cards */
  .metrics {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    margin-bottom: 14px;
  }}
  .metric {{
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 8px 10px;
  }}
  .metric-label {{ font-size: 8.5pt; color: #666; }}
  .metric-value {{ font-size: 16pt; font-weight: 700; color: #111; line-height: 1.25; }}
  .metric-sub {{ font-size: 8.5pt; color: #555; margin-top: 3px; }}

  /* Section */
  .section {{ margin-bottom: 14px; }}
  .section-title {{
    font-size: 12pt;
    font-weight: 700;
    color: #1e3a8a;
    border-bottom: 1.5px solid #cbd5e1;
    padding-bottom: 3px;
    margin-bottom: 8px;
  }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  ul {{ margin: 2px 0 0 20px; padding: 0; }}
  li {{ margin-bottom: 4px; }}

  /* 強項主題卡 — 緊湊版 */
  .s-card {{
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 5px;
    padding: 6px 11px;
    margin-bottom: 5px;
    page-break-inside: avoid;
  }}
  .s-card-title {{ font-weight: 600; color: #166534; font-size: 10pt; }}
  .s-card-count {{ font-weight: 400; font-size: 8.5pt; color: #555; }}
  .s-quote {{ font-size: 9pt; color: #333; margin: 2px 0 2px; font-style: italic; padding-left: 7px; border-left: 2px solid #bbf7d0; line-height: 1.45; }}
  .s-meta {{ font-size: 8pt; color: #666; }}

  /* 失敗原因/行為斷點 */
  .reason-row, .theme-row {{
    display: grid;
    grid-template-columns: 150px 1fr;
    gap: 8px;
    align-items: center;
    margin-bottom: 4px;
  }}
  .reason-label, .theme-label {{ font-size: 9.5pt; }}
  .reason-bar-wrap, .theme-bar-wrap {{
    position: relative;
    background: #f1f5f9;
    height: 18px;
    border-radius: 3px;
  }}
  .reason-bar {{ background: linear-gradient(90deg, #b91c1c, #dc2626); height: 100%; border-radius: 3px; }}
  .theme-bar {{ background: linear-gradient(90deg, #0891b2, #06b6d4); height: 100%; border-radius: 3px; }}
  .reason-count, .theme-count {{
    position: absolute;
    right: 6px;
    top: 0;
    font-size: 9pt;
    color: #333;
    line-height: 18px;
  }}

  /* 改進建議 — 大卡片 */
  .imp-card {{
    background: #fff;
    border: 1px solid #fca5a5;
    border-left: 4px solid #dc2626;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 14px;
    page-break-inside: avoid;
  }}
  .imp-head {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }}
  .imp-num {{
    font-size: 14pt;
    font-weight: 700;
    color: #dc2626;
  }}
  .imp-title {{
    font-size: 12pt;
    font-weight: 600;
    color: #1a1a1a;
  }}
  .imp-meta {{
    font-size: 9pt;
    color: #666;
    margin-left: auto;
  }}
  .imp-sub {{
    font-size: 9.5pt;
    font-weight: 600;
    color: #555;
    margin-top: 10px;
    margin-bottom: 4px;
  }}
  .imp-quote {{
    background: #f8fafc;
    border-left: 3px solid #94a3b8;
    padding: 8px 12px;
    font-size: 10pt;
    line-height: 1.5;
    color: #334155;
    font-style: italic;
  }}
  .imp-body {{
    font-size: 10pt;
    line-height: 1.6;
    background: #fffbeb;
    border-radius: 4px;
    padding: 8px 12px;
  }}
  .imp-pattern {{
    margin-top: 10px;
    font-size: 9.5pt;
    color: #555;
    background: #f1f5f9;
    padding: 6px 10px;
    border-radius: 4px;
  }}
  .missed {{ margin: 4px 0 4px 22px; padding: 0; font-size: 9.5pt; color: #444; }}
  .missed li {{ margin-bottom: 2px; }}

  /* Q list */
  .qlist {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px 10px 34px; }}
  .qlist li {{ margin-bottom: 6px; font-size: 10.5pt; }}

  /* Action cards */
  .act-card {{
    background: #fff;
    border: 1px solid #fcd34d;
    border-left: 4px solid #d97706;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 10px;
    page-break-inside: avoid;
  }}
  .act-head {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
  }}
  .act-num {{
    font-size: 13pt;
    font-weight: 700;
    color: #d97706;
  }}
  .act-title {{
    font-size: 11.5pt;
    font-weight: 600;
    color: #1a1a1a;
  }}
  .act-why {{
    background: #fef3c7;
    padding: 5px 10px;
    border-radius: 3px;
    font-size: 9.5pt;
    margin-bottom: 6px;
  }}
  .act-sub {{
    font-size: 9.5pt;
    font-weight: 600;
    color: #555;
    margin-top: 6px;
    margin-bottom: 3px;
  }}
  .act-how {{ margin: 2px 0 4px 22px; padding: 0; font-size: 10pt; }}
  .act-how li {{ margin-bottom: 2px; }}
  .act-metric {{
    background: #ecfdf5;
    border: 1px solid #a7f3d0;
    padding: 5px 10px;
    border-radius: 3px;
    font-size: 9.5pt;
    margin-top: 6px;
  }}
  .act-cited {{
    font-size: 9pt;
    color: #6b4e17;
    background: #fffbeb;
    border-left: 2px solid #f59e0b;
    padding: 3px 8px;
    margin: 2px 0 6px;
    border-radius: 2px;
  }}

  /* Tracking */
  .track-box {{
    background: #f0f9ff;
    border: 1px solid #bae6fd;
    border-radius: 6px;
    padding: 10px 14px;
    margin-top: 8px;
    page-break-inside: avoid;
  }}
  .track-list {{ margin: 2px 0 0 22px; padding: 0; font-size: 10pt; }}
  .track-list li {{ margin-bottom: 5px; }}

  /* Footer */
  .footer {{
    margin-top: 16px;
    padding-top: 8px;
    border-top: 1px solid #e5e7eb;
    font-size: 8.5pt;
    color: #888;
    text-align: center;
  }}

  /* Page break hints */
  .page-break {{ page-break-before: always; }}
</style>
</head>
<body>
<div class="page-container">

  <div class="hdr">
    <div>
      <div class="hdr-title">{esc(lw['name'])} 律師 · 1-on-1 備忘單</div>
      <div class="hdr-sub">{esc(lw['office'])} · {len(llm)} 筆有會議記錄案件經 AI 逐案歸因</div>
      <div class="focus-tag">🎯 {focus_title}</div>
    </div>
    <div class="hdr-meta">
      日期：{today}<br>
      資料期間：{prep['_metadata']['data_snapshot']}<br>
      分析模型：AI 語言模型
    </div>
  </div>

  <div class="narrative">{narrative}</div>
  {trend_narrative}

  <div class="metrics">
    <div class="metric">
      <div class="metric-label">整體成案率</div>
      <div class="metric-value">{fmt_pct(ov['sign_rate'])}</div>
      <div class="metric-sub">全所 {fmt_pct(ov['firm_sign_rate'])} · 同所別 {fmt_pct(ov.get('office_sign_rate') or 0)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">客單價（收款/簽）</div>
      <div class="metric-value">{fmt_money(ov['avg_collected'])}</div>
      <div class="metric-sub">全所 {fmt_money(ov.get('firm_avg_unit') or 0)} · 同所別 {fmt_money(ov.get('office_avg_unit') or 0)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">諮詢效益（收款/諮詢）</div>
      <div class="metric-value">{fmt_money(ov['consult_eff'])}</div>
      <div class="metric-sub">全所 {fmt_money(ov['firm_eff'])} · 同所別 {fmt_money(ov.get('office_eff') or 0)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">近3月 vs 前3月</div>
      <div class="metric-value" style="font-size:11pt;line-height:1.3;">
        成案 {fmt_delta(delta['sign_rate_delta'])}<br>
        效益 {fmt_delta(delta['consult_eff_delta']/1000, '千')}
      </div>
    </div>
  </div>
  <div style="font-size:8.5pt;color:#64748b;margin:-6px 0 10px 2px;">
    「同所別」= {esc(ov.get('office') or '(未標)')}（不含本人、{ov.get('office_peer_count', 0)} 位同事）— 排除合署/司法官合署等結構不同的所別以更公平比較
  </div>

  {recent_breakdown_html}

  {monthly_trend_html}

  {method_table_html}

  {unspecified_html}

  {lag_html}

  <div class="two-col section">
    <div>
      <div class="section-title">💰 已成案客單價 · 強項</div>
      <p class="small" style="margin:0 0 4px;color:#666;">※ 僅看已成案案件（未成案的分類可靠性低），與全所同類別比較</p>
      <ul>{strength_rows}</ul>
    </div>
    <div>
      <div class="section-title">💸 已成案客單價 · 弱項</div>
      <p class="small" style="margin:0 0 4px;color:#666;">※ 僅看已成案案件，報價/折讓空間的線索</p>
      <ul>{weakness_rows}</ul>
    </div>
  </div>

  {trend_table_html}

  <div class="section">
    <div class="section-title">✨ 諮詢中做得好的 4 件事（AI 從 {len(signed)} 筆已簽案件歸納）</div>
    {strength_cards}
  </div>

  <div class="section">
    <div class="section-title">🔧 下次可以更好的 3 件事（配代表案例 · 從會議記錄原文出發）</div>
    <p class="small" style="margin:0 0 10px;">以下每則建議都由 AI 從該筆諮詢會議記錄、逐字稿中讀出來，並標註<b>原文證據</b>與<b>律師當下錯過的動作</b>，方便 1-on-1 現場討論時回想情境。</p>
    {improvement_cards}
  </div>

  <div class="two-col section" style="page-break-inside: avoid;">
    <div>
      <div class="section-title">🔍 未簽案件失敗原因集中度（n={len(unsigned)}）</div>
      {reason_rows}
    </div>
    <div>
      <div class="section-title">🎬 律師錯過的動作主題</div>
      {theme_rows}
    </div>
  </div>

  <div class="section">
    <div class="section-title">❓ 會議討論問題</div>
    <ol class="qlist">
      {questions_html}
    </ol>
  </div>

  <div class="section">
    <div class="section-title">🎯 後續行動重點（會議後落地執行）</div>
    {action_cards}
  </div>

  <div class="section">
    <div class="section-title">📈 追蹤機制</div>
    {tracking_html}
  </div>

  <div class="footer">
    由 AI 對 {len(llm)} 筆諮詢會議記錄進行逐案歸因分析生成 · 所有引用、統計、歸因理由均源自原始諮詢記錄與逐字稿 · 生成日期 {today}
  </div>

</div>
</body>
</html>"""
    return html_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--no-llm-actions", action="store_true",
                    help="停用 LLM 個人化 actions，退回 rule-based 模板")
    args = ap.parse_args()

    global _USE_LLM_ACTIONS
    if args.no_llm_actions:
        _USE_LLM_ACTIONS = False

    prep_path = RAW_DIR / f"{args.name}_prep.json"
    llm_path = RAW_DIR / f"{args.name}_llm.json"
    if not prep_path.exists():
        print(f"找不到 {prep_path}"); sys.exit(1)
    if not llm_path.exists():
        print(f"找不到 {llm_path}"); sys.exit(1)

    prep = json.loads(prep_path.read_text(encoding="utf-8"))
    llm = json.loads(llm_path.read_text(encoding="utf-8"))

    print(f"律師：{args.name}")
    print(f"  prep 案件數：{prep['_metadata']['cases_with_mr_count']}")
    print(f"  llm 分析數：{len(llm)}")

    # 拉所有案件（不只有會議記錄）以做案型趨勢分析
    all_cases = None
    lag_stats = None
    if _URL and _KEY:
        try:
            all_cases = fetch_lawyer_cases(prep["lawyer"]["id"])
            print(f"  DB 全案件數：{len(all_cases)}")
            # 算簽約滯後分布
            lag_stats = compute_sign_lag_stats(prep["lawyer"]["name"], all_cases)
            if lag_stats:
                print(f"  簽約 lag：中位 {lag_stats['median']} 天、平均 {lag_stats['mean']:.0f} 天、{lag_stats['within_30']:.0f}% 在 30 天內")
        except Exception as e:
            print(f"  [warn] 抓不到全案件 / lag：{e}")

    html_out = build_html(prep, llm, all_cases=all_cases, lag_stats=lag_stats)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / f"{args.name}_brief.html"
    html_path.write_text(html_out, encoding="utf-8")
    print(f"HTML：{html_path}")

    if args.html_only:
        return

    from playwright.sync_api import sync_playwright
    pdf_path = OUT_DIR / f"{args.name}_brief.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file:///{html_path.as_posix()}")
        page.emulate_media(media="print")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            margin={"top": "12mm", "right": "14mm", "bottom": "12mm", "left": "14mm"},
            print_background=True,
        )
        browser.close()

    print(f"PDF：{pdf_path}")


if __name__ == "__main__":
    main()
