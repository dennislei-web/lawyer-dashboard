"""
Wave 2 Step 2：LLM 歸因分析
- 輸入：briefs/raw_data/{律師名}_prep.json
- 對該律師所有有會議記錄的案件送 Claude 分析
- 輸出：
  1. briefs/raw_data/{律師名}_llm.json（分析結果）
  2. 寫回 Supabase consultation_cases.llm_analysis 欄位

用法：
  python llm_analyze_cases.py --name 洪琬琪
  python llm_analyze_cases.py --name 洪琬琪 --dry-run   # 不寫回 DB
  python llm_analyze_cases.py --name 洪琬琪 --limit 3   # 只跑 3 筆測試
"""
import os, io, sys, json, argparse, time
from pathlib import Path
from datetime import datetime
from collections import deque
import httpx
from dotenv import load_dotenv
from anthropic import Anthropic, RateLimitError

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1.1"  # v1.1: 加 reason_specific 自由文字欄位（破除 enum 同質化）

# Rate limit：10,000 input tokens/min。保留 10% 緩衝 → 9,000
TOKEN_LIMIT_PER_MIN = 9000
_token_log = deque()  # (timestamp, input_tokens)


def throttle_for_budget(estimated_tokens):
    """在呼叫前等待直到 60 秒滾動窗口內還能容納 estimated_tokens"""
    while True:
        now = time.time()
        while _token_log and now - _token_log[0][0] > 60:
            _token_log.popleft()
        used = sum(t for _, t in _token_log)
        if used + estimated_tokens <= TOKEN_LIMIT_PER_MIN:
            return
        # 單筆就超過 60 秒窗口上限，等也沒用（log 空了也還是炸），交給 SDK retry
        if not _token_log:
            print(f"  [warn] 預估 {estimated_tokens}tk 單筆就超過 {TOKEN_LIMIT_PER_MIN}tk/min 上限，直接送出讓 SDK retry 處理", flush=True)
            return
        wait = 60 - (now - _token_log[0][0]) + 1
        if wait <= 0:
            return
        print(f"  [throttle] 窗口內已用 {used}tk, 此筆預估 {estimated_tokens}tk, 等 {wait:.0f}s", flush=True)
        time.sleep(wait)


def record_tokens(actual_tokens):
    _token_log.append((time.time(), actual_tokens))

PROMPT_TEMPLATE = """你是法律諮詢成案分析專家。以下是一場法律諮詢的完整會議記錄，以及該次諮詢**是否成交**。

請客觀分析，所有判斷必須基於會議記錄原文（可引用逐字稿）。不要臆測會議外的事實。

## 案件資訊
- 案件類型：{case_type}
- 是否簽約：{is_signed_label}
- 案件日期：{case_date}
- 收款金額：{collected}
- 律師事後備註：{lawyer_notes}

## 會議記錄
\"\"\"
{meeting_record}
\"\"\"

{transcript_section}

## 分析任務

請輸出**純 JSON**（不要 markdown 包裝、不要額外說明），schema 如下：

{{
  "failure_reason": "<以下 7 類擇一，若簽約案填「已簽約」>：價格疑慮 / 需求不符（客戶要的不在本所擅長範圍）/ 律師未建立信任 / 客戶決策延遲（回去考慮、跟家人討論）/ 案件難度過高 / 客戶個人因素（經濟、時間、關係變化）/ 其他 / 已簽約",
  "reason_specific": "<這個案件**獨特**的卡點，1 句 15-30 字。必須包含當下情境細節，禁止寫泛用句。範例：『對造已給 blank check、律師卻繼續講親權技術細節 45 分鐘』、『客戶帶媽媽舅舅來找 second opinion，律師沒挑一審書狀具體可改之處』。簽約案寫『已簽約』即可>",
  "reason_evidence": "<從會議記錄引用 1-3 句能支持上述歸因的原文，用「」框起>",
  "missed_opportunities": ["<律師明顯錯過的關鍵轉機，每項 1 句。**禁止**寫泛用詞如『未當場報價』『未探預算』『未強化委任價值』；必須帶情境細節，如『律師講完三條訴訟路徑後沒回應客戶問的「打到底要多少錢」』。簽約案此陣列可空>"],
  "strengths": ["<律師做得好的地方，1-3 項，每項 1 句>"],
  "improvement_for_lawyer": "<針對這位律師的個人化改進建議，1 段 2-4 句。具體、可執行。對簽約案仍可指出『下次可更好的地方』>",
  "transferable_pattern": "<這個案件對類似情境的通用教訓，1 句>"
}}

**重要**：
- reason_evidence 必須逐字引用會議記錄原文
- **reason_specific 是這個 case 的「指紋」**，不是 failure_reason bucket 的同義改寫；若想不出個案細節就不要寫泛用句，寧願短也要具體
- missed_opportunities 是**律師可以做但沒做**的事，不是客戶的問題；每項都要帶當下情境（什麼時刻、什麼話題之後、應該說什麼）
- improvement_for_lawyer 要像主管給下屬的具體指導，不是空泛的「要更專業」
"""


def fetch_lawyer_id_by_name(name):
    r = httpx.get(
        f"{URL}/rest/v1/lawyers",
        params={"select": "id,name", "name": f"eq.{name}"},
        headers=HDR, timeout=30
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError(f"找不到律師：{name}")
    return rows[0]["id"]


def analyze_case(client, case):
    """呼叫 Claude 分析單一案件，回傳解析後的 dict 或 None"""
    mr = case.get("meeting_record") or ""
    ts = case.get("transcript") or ""
    # 避免過長，meeting_record 上限 25k chars，transcript 15k chars
    if len(mr) > 25000:
        mr = mr[:25000] + "\n...(截斷)"
    if len(ts) > 15000:
        ts = ts[:15000] + "\n...(截斷)"

    transcript_section = ""
    if ts and ts.strip():
        transcript_section = f"## 逐字稿（節錄）\n\"\"\"\n{ts}\n\"\"\"\n"

    prompt = PROMPT_TEMPLATE.format(
        case_type=case.get("case_type") or "(未填)",
        is_signed_label="已簽約" if case.get("is_signed") else "未簽約",
        case_date=case.get("case_date") or "",
        collected=f"${int(case.get('collected') or 0):,}" if case.get("is_signed") else "—",
        lawyer_notes=case.get("lawyer_notes") or "(無)",
        meeting_record=mr,
        transcript_section=transcript_section,
    )

    # 預估 input tokens（中文約 0.7 tokens/char，prompt 大約 1:1），用 prompt 長度粗估
    estimated_in = int(len(prompt) * 0.7) + 200
    throttle_for_budget(estimated_in)

    # 呼叫（RateLimitError 自己再 retry 一次，避開 SDK 偶發）
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except RateLimitError as e:
            wait = 35 + attempt * 15
            print(f"  [429 retry {attempt+1}/3] 等 {wait}s", flush=True)
            time.sleep(wait)
    else:
        raise RuntimeError("rate limit 重試 3 次仍失敗")

    record_tokens(resp.usage.input_tokens)
    text = resp.content[0].text.strip()
    # 容錯：如果模型包了 ```json ... ```
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [JSON parse error]: {e}")
        print(f"  raw output: {text[:500]}")
        return None, resp.usage

    # 加 metadata
    data["_model"] = MODEL
    data["_prompt_version"] = PROMPT_VERSION
    data["_analyzed_at"] = datetime.utcnow().isoformat() + "Z"
    return data, resp.usage


def write_back_to_db(case_id, analysis):
    """把 analysis 寫回 consultation_cases"""
    r = httpx.patch(
        f"{URL}/rest/v1/consultation_cases",
        params={"id": f"eq.{case_id}"},
        json={
            "llm_analysis": analysis,
            "llm_analyzed_at": datetime.utcnow().isoformat() + "Z",
        },
        headers={**HDR, "Prefer": "return=minimal"},
        timeout=30,
    )
    if r.status_code not in (200, 204):
        print(f"  [DB write error {r.status_code}]: {r.text[:300]}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry-run", action="store_true", help="不寫回 DB，只存本地 JSON")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 筆（測試用）")
    ap.add_argument("--force", action="store_true", help="重跑已分析過的案件")
    args = ap.parse_args()

    prep_path = SCRIPT_DIR / "briefs" / "raw_data" / f"{args.name}_prep.json"
    if not prep_path.exists():
        print(f"找不到 prep 檔：{prep_path}")
        print("請先跑：python prep_1on1_data.py --name " + args.name)
        sys.exit(1)

    prep = json.loads(prep_path.read_text(encoding="utf-8"))
    cases = prep["cases_with_meeting_record"]

    if args.limit:
        cases = cases[:args.limit]

    print(f"律師：{args.name}")
    print(f"會議記錄案件數：{len(cases)}")
    print(f"Model：{MODEL}")
    print(f"Dry run：{args.dry_run}")
    print()

    # 查哪些已經分析過（避免重跑浪費）
    if not args.force:
        ids_str = ",".join(f'"{c["id"]}"' for c in cases)
        if ids_str:
            r = httpx.get(
                f"{URL}/rest/v1/consultation_cases",
                params={
                    "select": "id,llm_analysis",
                    "id": f"in.({ids_str})",
                    "llm_analysis": "not.is.null",
                },
                headers=HDR, timeout=30
            )
            if r.status_code == 200:
                already_done = {row["id"] for row in r.json()}
                if already_done:
                    print(f"跳過已分析過的 {len(already_done)} 筆（用 --force 可重跑）")
                    cases = [c for c in cases if c["id"] not in already_done]

    if not cases:
        print("沒有新案件要分析。")
        return

    client = Anthropic(api_key=ANTHROPIC_KEY, max_retries=10, timeout=120)

    results = []
    total_in, total_out = 0, 0
    ok, fail = 0, 0

    for i, case in enumerate(cases, 1):
        mr_len = len(case.get("meeting_record") or "")
        print(f"[{i}/{len(cases)}] {case.get('case_date')} {case.get('case_type')} "
              f"({'簽' if case.get('is_signed') else '未簽'}) mr={mr_len}字", flush=True)

        if mr_len < 50:
            print("  [skip] meeting_record 太短")
            fail += 1
            continue

        try:
            analysis, usage = analyze_case(client, case)
        except Exception as e:
            print(f"  [error] {e}")
            fail += 1
            continue

        if analysis is None:
            fail += 1
            continue

        total_in += usage.input_tokens
        total_out += usage.output_tokens

        print(f"  ✓ failure_reason={analysis.get('failure_reason')} "
              f"(tokens in={usage.input_tokens} out={usage.output_tokens})")

        results.append({
            "case_id": case["id"],
            "case_date": case.get("case_date"),
            "case_type": case.get("case_type"),
            "is_signed": case.get("is_signed"),
            "collected": case.get("collected"),
            "analysis": analysis,
        })

        if not args.dry_run:
            if write_back_to_db(case["id"], analysis):
                pass  # 成功
            else:
                print("  [warn] DB 寫入失敗，但本地 JSON 會留存")

        ok += 1
        # 節流已由 throttle_for_budget 處理，這裡不再額外 sleep

    # 存結果（merge 舊檔：同 case_id 的新分析覆蓋舊的，其餘保留）
    out_path = SCRIPT_DIR / "briefs" / "raw_data" / f"{args.name}_llm.json"
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    new_ids = {r["case_id"] for r in results}
    merged = [e for e in existing if e.get("case_id") not in new_ids] + results
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"合併後總筆數：{len(merged)}（本次新增/更新 {len(results)}）")

    print()
    print(f"完成：成功 {ok}、失敗 {fail}")
    print(f"Tokens：in={total_in:,} out={total_out:,}")
    # Sonnet 4.5 價格：$3/M input, $15/M output
    cost = total_in / 1_000_000 * 3 + total_out / 1_000_000 * 15
    print(f"估算成本：${cost:.3f} USD")
    print(f"結果：{out_path}")


if __name__ == "__main__":
    main()
