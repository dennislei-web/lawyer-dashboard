"""
Inline batch helper for lawyer 1-on-1 brief LLM analysis.

Two modes:
  dump  — print next N unanalyzed cases (meeting_record + transcript) to stdout
  write — read analyses JSON from file, write to DB + accumulate llm.json

Usage:
  python inline_batch.py dump --name 黃顯皓 --n 4
  python inline_batch.py write --name 黃顯皓 --file batch_in.json
"""
import os, io, sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / ".env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

RAW_DIR = SCRIPT_DIR / "briefs" / "raw_data"


def load_prep(name):
    return json.loads((RAW_DIR / f"{name}_prep.json").read_text(encoding="utf-8"))


def load_llm(name):
    p = RAW_DIR / f"{name}_llm.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def save_llm(name, data):
    (RAW_DIR / f"{name}_llm.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_dump(name, n):
    prep = load_prep(name)
    cases = prep.get("cases_with_meeting_record", [])
    llm = load_llm(name)
    done_ids = {x["case_id"] for x in llm}
    pending = [c for c in cases if c["id"] not in done_ids]
    total_done = len(done_ids)
    total = len(cases)
    batch = pending[:n]

    out = {
        "lawyer": name,
        "progress": f"{total_done}/{total} done, {len(pending)} pending",
        "batch_size": len(batch),
        "cases": [],
    }
    for c in batch:
        mr = c.get("meeting_record") or ""
        ts = c.get("transcript") or ""
        # Trim for inline read budget. meeting_record is the structured summary
        # (most of the analytical value); transcript is supporting color.
        # Default: meeting_record only (cap 12K chars), transcript dropped.
        # If env INLINE_INCLUDE_TRANSCRIPT=1, include capped transcript.
        if len(mr) > 12000:
            mr = mr[:12000] + "\n...(截斷)"
        if os.environ.get("INLINE_INCLUDE_TRANSCRIPT") == "1":
            if len(ts) > 4000:
                ts = ts[:4000] + "\n...(截斷)"
        else:
            ts = ""
        out["cases"].append({
            "id": c["id"],
            "case_date": c.get("case_date"),
            "case_type": c.get("case_type"),
            "case_number": c.get("case_number"),
            "client_name": c.get("client_name"),
            "is_signed": c.get("is_signed"),
            "collected": c.get("collected"),
            "revenue": c.get("revenue"),
            "lawyer_notes": c.get("lawyer_notes"),
            "meeting_record": mr,
            "transcript": ts,
        })

    out_path = RAW_DIR / f"{name}_batch_in.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"dumped {len(batch)} cases to {out_path}")
    print(f"progress: {out['progress']}")


def cmd_write(name, file):
    """file format:
    [
      {"case_id": "...", "analysis": {failure_reason, reason_specific, reason_evidence,
                                       missed_opportunities, strengths, improvement_for_lawyer,
                                       transferable_pattern}},
      ...
    ]
    """
    batch = json.loads(Path(file).read_text(encoding="utf-8"))
    if not isinstance(batch, list):
        raise SystemExit("file must be a JSON array")

    # build lookup of case meta from prep for llm.json
    prep = load_prep(name)
    case_meta = {c["id"]: c for c in prep.get("cases_with_meeting_record", [])}
    llm = load_llm(name)
    done_ids = {x["case_id"] for x in llm}
    now_iso = datetime.now(timezone.utc).isoformat()

    written_db = 0
    appended_json = 0
    for item in batch:
        cid = item["case_id"]
        analysis = item["analysis"]

        # write DB
        r = httpx.patch(
            f"{URL}/rest/v1/consultation_cases",
            params={"id": f"eq.{cid}"},
            headers={**HDR, "Prefer": "return=minimal"},
            json={
                "llm_analysis": analysis,
                "llm_analyzed_at": now_iso,
            },
            timeout=30,
        )
        r.raise_for_status()
        written_db += 1

        # update or append llm.json
        meta = case_meta.get(cid, {})
        entry = {
            "case_id": cid,
            "case_date": meta.get("case_date"),
            "case_type": meta.get("case_type"),
            "is_signed": meta.get("is_signed"),
            "collected": meta.get("collected"),
            "analysis": analysis,
        }
        if cid in done_ids:
            for i, x in enumerate(llm):
                if x["case_id"] == cid:
                    llm[i] = entry
                    break
        else:
            llm.append(entry)
            appended_json += 1
            done_ids.add(cid)

    save_llm(name, llm)
    print(f"wrote {written_db} to DB; appended {appended_json} to llm.json (total {len(llm)})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--name", required=True)
    d.add_argument("--n", type=int, default=4)
    w = sub.add_parser("write")
    w.add_argument("--name", required=True)
    w.add_argument("--file", required=True)
    args = ap.parse_args()

    if args.cmd == "dump":
        cmd_dump(args.name, args.n)
    elif args.cmd == "write":
        cmd_write(args.name, args.file)


if __name__ == "__main__":
    main()
