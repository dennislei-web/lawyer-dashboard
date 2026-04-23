"""
Resume LLM 分析（短 timeout 版）— 針對 llm_analyze_cases.py hang 的補救
- 跳過已分析
- 單筆 timeout=60s, max_retries=2
- 單筆失敗直接跳下一筆，不卡住整個 batch
"""
import os, io, sys, json, time
from pathlib import Path
from datetime import datetime
from collections import deque
import httpx
from dotenv import load_dotenv
from anthropic import Anthropic, APITimeoutError, APIConnectionError

os.environ["PYTHONIOENCODING"] = "utf-8"
# 不再包 sys.stdout，改靠 PYTHONIOENCODING（避免 pipe 時 buffer 被關）
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

MODEL = "claude-sonnet-4-5"
PROMPT_VERSION = "v1.0"

# Import the prompt template from main script
sys.path.insert(0, str(SCRIPT_DIR))
from llm_analyze_cases import PROMPT_TEMPLATE, throttle_for_budget, record_tokens

NAME = sys.argv[1] if len(sys.argv) > 1 else "劉奕靖"

prep = json.load(open(SCRIPT_DIR / "briefs" / "raw_data" / f"{NAME}_prep.json", encoding="utf-8"))
cases = prep["cases_with_meeting_record"]
LID = prep["lawyer"]["id"]

# Skip already done
ids_str = ",".join(f'"{c["id"]}"' for c in cases)
r = httpx.get(
    f"{URL}/rest/v1/consultation_cases",
    params={"select": "id", "id": f"in.({ids_str})", "llm_analysis": "not.is.null"},
    headers=HDR, timeout=30,
)
already_done = {row["id"] for row in r.json()}
pending = [c for c in cases if c["id"] not in already_done]
print(f"律師：{NAME}  全部 {len(cases)}  已完成 {len(already_done)}  待處理 {len(pending)}", flush=True)

client = Anthropic(api_key=ANTHROPIC_KEY, max_retries=2, timeout=90)

ok, fail = 0, 0
failed_cases = []

for i, case in enumerate(pending, 1):
    mr = case.get("meeting_record") or ""
    ts = case.get("transcript") or ""
    mr_len = len(mr)
    client_name = case.get("client_name") or "?"
    cn = case.get("case_number", "")

    print(f"[{i}/{len(pending)}] {case.get('case_date')} {client_name} {cn} "
          f"({'簽' if case.get('is_signed') else '未簽'}) mr={mr_len}字 ts={len(ts)}字", flush=True)

    if mr_len < 50:
        print("  [skip] mr 太短")
        fail += 1
        continue

    if len(mr) > 25000:
        mr = mr[:25000] + "\n...(截斷)"
    if len(ts) > 15000:
        ts = ts[:15000] + "\n...(截斷)"

    transcript_section = f'## 逐字稿（節錄）\n"""\n{ts}\n"""\n' if ts.strip() else ""

    prompt = PROMPT_TEMPLATE.format(
        case_type=case.get("case_type") or "(未填)",
        is_signed_label="已簽約" if case.get("is_signed") else "未簽約",
        case_date=case.get("case_date") or "",
        collected=f"${int(case.get('collected') or 0):,}" if case.get("is_signed") else "—",
        lawyer_notes=case.get("lawyer_notes") or "(無)",
        meeting_record=mr,
        transcript_section=transcript_section,
    )

    estimated_in = int(len(prompt) * 0.7) + 200
    throttle_for_budget(estimated_in)

    try:
        t0 = time.time()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - t0
        record_tokens(resp.usage.input_tokens)
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().rstrip("`").strip()
        data = json.loads(text)
        data["_model"] = MODEL
        data["_prompt_version"] = PROMPT_VERSION
        data["_analyzed_at"] = datetime.utcnow().isoformat() + "Z"

        # Write to DB
        wr = httpx.patch(
            f"{URL}/rest/v1/consultation_cases",
            params={"id": f"eq.{case['id']}"},
            json={"llm_analysis": data, "llm_analyzed_at": datetime.utcnow().isoformat() + "Z"},
            headers={**HDR, "Prefer": "return=minimal"},
            timeout=30,
        )
        if wr.status_code in (200, 204):
            ok += 1
            print(f"  ✓ {data.get('failure_reason','?')} ({elapsed:.1f}s, in={resp.usage.input_tokens} out={resp.usage.output_tokens})", flush=True)
        else:
            print(f"  [DB write err {wr.status_code}]: {wr.text[:200]}")
            fail += 1
            failed_cases.append(case["id"])
    except (APITimeoutError, APIConnectionError) as e:
        print(f"  [timeout/conn error] {type(e).__name__}: {e}", flush=True)
        fail += 1
        failed_cases.append(case["id"])
    except Exception as e:
        print(f"  [err] {type(e).__name__}: {e}", flush=True)
        fail += 1
        failed_cases.append(case["id"])

print(f"\n完成 {ok}/{len(pending)}  失敗 {fail}")
if failed_cases:
    print(f"失敗 case ids: {failed_cases}")
