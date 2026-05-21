"""
從 stdin 讀 JSONL（每行一個 {case_id, urgency, timing, suggested_message, emphasis_points, reasoning}），
upsert 到 consultation_ai_suggestions。
也可以 --file <path> 指定檔案。
"""
import os, sys, io, json, argparse
from pathlib import Path
from datetime import datetime
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

MODEL = "inline-claude-opus-4-7"
PROMPT_VERSION = "v1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=str, default=None, help="JSONL file (default stdin)")
    ap.add_argument("--data-sources-from", type=str, default=None,
                    help="補上 data_sources：從 pending_prompts.jsonl 撈，case_id 對應 data_sources")
    args = ap.parse_args()

    ds_map = {}
    if args.data_sources_from:
        with open(args.data_sources_from, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    ds_map[r["case_id"]] = r.get("data_sources", {})

    src = open(args.file, encoding="utf-8") if args.file else sys.stdin
    rows = []
    for line in src:
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))

    ok, fail = 0, 0
    now = datetime.utcnow().isoformat() + "Z"
    for r in rows:
        cid = r["case_id"]
        body = {
            "case_id": cid,
            "urgency": r.get("urgency"),
            "timing": r.get("timing"),
            "suggested_message": r.get("suggested_message"),
            "emphasis_points": r.get("emphasis_points"),
            "reasoning": r.get("reasoning"),
            "full_response": r,
            "data_sources": ds_map.get(cid, {}),
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "generated_at": now,
        }
        resp = httpx.post(
            f"{URL}/rest/v1/consultation_ai_suggestions?on_conflict=case_id",
            headers=HDR, json=body, timeout=30,
        )
        if resp.status_code < 300:
            ok += 1
            print(f"  OK {cid[:8]} {r.get('urgency','?')} {r.get('timing','')[:20]}")
        else:
            fail += 1
            print(f"  FAIL {cid[:8]} {resp.status_code}: {resp.text[:200]}", file=sys.stderr)

    print(f"\nupserted ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
