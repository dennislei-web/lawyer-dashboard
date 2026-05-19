"""
寫入單筆 AI 建議到 consultation_ai_suggestions。
用法：
    python upsert_ai_suggestion.py <case_id> --json '{"urgency":"high","timing":"...","suggested_message":"...",...}'
    cat sugg.json | python upsert_ai_suggestion.py <case_id>  # 從 stdin
"""
import os, io, sys, json, argparse
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv("/Users/dennislei/projects/lawyer-dashboard/scripts/.env")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("--json", type=str, default=None, help="JSON payload (或從 stdin 讀)")
    ap.add_argument("--data-sources", type=str, default=None, help="data_sources JSON")
    ap.add_argument("--model", type=str, default="inline-claude-opus-4-7")
    ap.add_argument("--prompt-version", type=str, default="v1")
    args = ap.parse_args()

    payload_str = args.json or sys.stdin.read()
    sugg = json.loads(payload_str)
    data_sources = json.loads(args.data_sources) if args.data_sources else (sugg.pop("_data_sources", None) or {})

    body = {
        "case_id": args.case_id,
        "urgency": sugg.get("urgency"),
        "timing": sugg.get("timing"),
        "suggested_message": sugg.get("suggested_message"),
        "emphasis_points": sugg.get("emphasis_points"),
        "reasoning": sugg.get("reasoning"),
        "full_response": sugg,
        "data_sources": data_sources,
        "model": args.model,
        "prompt_version": args.prompt_version,
    }
    r = httpx.post(
        f"{URL}/rest/v1/consultation_ai_suggestions?on_conflict=case_id",
        headers=HDR,
        json=body,
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"FAIL {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)
    print(f"OK case_id={args.case_id}  urgency={sugg.get('urgency')}")


if __name__ == "__main__":
    main()
