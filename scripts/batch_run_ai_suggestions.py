"""
批次跑 AI 追單建議：讀 prepare_pending_prompts.py 輸出的 JSONL，呼叫 Claude，upsert 進 consultation_ai_suggestions。

用法：
    python scripts/prepare_pending_prompts.py            # 先 dump JSONL
    python scripts/batch_run_ai_suggestions.py           # 跑全部（自動 skip 已有 suggestion 的）
    python scripts/batch_run_ai_suggestions.py --force   # 重跑（覆蓋現有 suggestion）
    python scripts/batch_run_ai_suggestions.py --limit 5
"""
import os, io, sys, json, argparse, time
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import deque
import httpx
from dotenv import load_dotenv
from anthropic import Anthropic, RateLimitError

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
HDR_W = {**HDR, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

import tempfile
DEFAULT_INPUT = str(Path(tempfile.gettempdir()) / "pending_prompts.jsonl")

MODEL = "claude-opus-4-5-20250930"  # opus 4.5 sufficient; opus 4.7 is heavier and inline-tier
PROMPT_VERSION = "v1"

# Anthropic rate limit safety
TOKEN_LIMIT_PER_MIN = 20000
_token_log = deque()


def throttle(est):
    while True:
        now = time.time()
        while _token_log and now - _token_log[0][0] > 60:
            _token_log.popleft()
        used = sum(t for _, t in _token_log)
        if used + est <= TOKEN_LIMIT_PER_MIN:
            return
        if not _token_log:
            return
        wait = 60 - (now - _token_log[0][0]) + 1
        if wait > 0:
            print(f"  [throttle] used {used}tk, est {est}tk → wait {wait:.0f}s", flush=True)
            time.sleep(wait)


PROMPT = """你是喆律法律事務所的接案追單 AI 助手。
接案同仁需要對一件「諮詢後沒簽約」的案件做 follow-up，請依現有資料生成一段可直接複製貼 LINE 的話術。

## 案件資料
- 諮詢日：{case_date}（{days_ago} 天前）
- 案件類型：{case_type}
- 當事人：{client_name}
- 諮詢律師：{lawyer_name}
- 接案同仁：{tracking_staff}

### tracking_notes（諮詢後速記，CRM 同步）
{tracking_notes_block}

### lawyer_notes（律師的追單建議）
{lawyer_notes_block}

### meeting_record（會議記錄摘錄，前 800 字）
{meeting_record_block}

### LINE 連結狀態
{line_status}

## 任務：請輸出純 JSON（不要 markdown 包裝、不要多餘文字），schema：

{{
  "urgency": "high | medium | low",
  "timing": "<具體建議何時聯絡，1 句口語，例：今天傍晚、明天早上、這週四前、再等一週>",
  "suggested_message": "<可直接複製貼 LINE 的話術，第一人稱（『我是喆律的[接案同仁名]』）、口語化、具體。多行用 \\n 分段>",
  "emphasis_points": "<本封 LINE 要強調的關鍵點，1 句>",
  "reasoning": "<為什麼這樣建議，1 句>"
}}

## 策略要點
- **三資料皆空（tracking_notes、lawyer_notes、meeting_record 全空）**：urgency=low，emphasis_points 直接標『⚠ 建議先補資料』，suggested_message 給最通用破冰並請客戶說出在意點。
- **諮詢日 ≤ 3 天 + 有報價或痛點**：urgency=high，今天傍晚或明早觸發。
- **客戶有提「想一想 / 比較 / 跟家人討論」**：urgency=medium，3-5 天後 follow-up，話術帶反向誘因（時效、案件惡化風險）。
- **諮詢日 > 14 天 + 無 LINE 連結**：urgency=low，破冰 + 試探是否還在處理。
- **有具體報價金額**：suggested_message 必須引用該金額（讓客戶秒記得是哪件）。
- **有特定優惠到期日**：當天或前 1 天觸發，urgency=high。
- 第一人稱用接案同仁名字（若 tracking_staff 是「賴佳瑩, 江欣柔」這種多人列就挑第一個）。
- 不要寫「請問您方便講電話嗎」這種空話；要帶具體下一步（試算金額、預約律師、寄資料）。

只回 JSON。"""


def build_prompt(item):
    tn = (item.get("tracking_notes") or "").strip()
    ln = (item.get("lawyer_notes") or "").strip()
    mr = (item.get("meeting_record_excerpt") or "").strip()
    line_url = (item.get("line_chat_url") or "").strip()

    def block(text, empty="（無）"):
        return text if text else empty

    line_status = "✓ 有 LINE 連結" if line_url else "✗ 無 LINE 連結（接案同仁未貼）"

    return PROMPT.format(
        case_date=item["case_date"],
        days_ago=item["days_ago"],
        case_type=item.get("case_type") or "（未填）",
        client_name=item.get("client_name") or "（未填）",
        lawyer_name=item.get("lawyer_name") or "?",
        tracking_staff=item.get("tracking_staff") or "（未指派）",
        tracking_notes_block=block(tn),
        lawyer_notes_block=block(ln),
        meeting_record_block=block(mr),
        line_status=line_status,
    )


def fetch_existing_case_ids():
    rows, off = [], 0
    while True:
        r = httpx.get(
            f"{URL}/rest/v1/consultation_ai_suggestions",
            params={"select": "case_id", "limit": "1000", "offset": str(off)},
            headers=HDR, timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < 1000:
            break
        off += 1000
    return {x["case_id"] for x in rows}


def upsert(case_id, sugg, data_sources):
    body = {
        "case_id": case_id,
        "urgency": sugg.get("urgency"),
        "timing": sugg.get("timing"),
        "suggested_message": sugg.get("suggested_message"),
        "emphasis_points": sugg.get("emphasis_points"),
        "reasoning": sugg.get("reasoning"),
        "full_response": sugg,
        "data_sources": data_sources,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    r = httpx.post(
        f"{URL}/rest/v1/consultation_ai_suggestions?on_conflict=case_id",
        headers=HDR_W, json=body, timeout=30,
    )
    return r.status_code < 300, (r.text if r.status_code >= 300 else "")


def parse_json_loose(text):
    """容錯 JSON parse — 處理 markdown 包裝"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip().rstrip("`").strip()
    return json.loads(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="重跑已有 suggestion 的 case")
    ap.add_argument("--start", type=int, default=0, help="跳過前 N 件（resume 用）")
    args = ap.parse_args()

    items = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))

    existing = set() if args.force else fetch_existing_case_ids()
    print(f"輸入：{len(items)} 件，已有 suggestion：{len(existing)} 件")

    if not args.force:
        items = [x for x in items if x["case_id"] not in existing]
        print(f"待跑：{len(items)} 件")
    if args.start:
        items = items[args.start:]
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("沒有要跑的。"); return

    client = Anthropic(api_key=ANTHROPIC_KEY, max_retries=5, timeout=120)

    ok, fail = 0, 0
    t0 = time.time()
    for i, item in enumerate(items, 1):
        cid = item["case_id"]
        cn = item.get("client_name", "?")
        prompt = build_prompt(item)
        est = int(len(prompt) * 0.7) + 500
        throttle(est)

        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except RateLimitError:
            print(f"  [429] sleep 60s", flush=True); time.sleep(60); fail += 1; continue
        except Exception as e:
            print(f"[{i}/{len(items)}] {cn}: ERROR {e}", flush=True); fail += 1; continue

        _token_log.append((time.time(), resp.usage.input_tokens))
        try:
            sugg = parse_json_loose(resp.content[0].text)
        except Exception as e:
            print(f"[{i}/{len(items)}] {cn}: PARSE FAIL {e}", flush=True)
            print(f"  raw: {resp.content[0].text[:200]}")
            fail += 1; continue

        ok_w, err = upsert(cid, sugg, item.get("data_sources", {}))
        if not ok_w:
            print(f"[{i}/{len(items)}] {cn}: DB FAIL {err[:200]}", flush=True); fail += 1; continue

        urg = sugg.get("urgency", "?")
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urg, "⚪")
        elapsed = time.time() - t0
        eta = (elapsed / i) * (len(items) - i)
        print(f"[{i}/{len(items)}] {emoji} {cn}  (in={resp.usage.input_tokens} out={resp.usage.output_tokens})  elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
        ok += 1

    print(f"\nDONE ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
