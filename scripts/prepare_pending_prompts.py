"""
準備未成案的 prompt 資料（JSONL）。
- 抓近 30 天 is_signed=false 且 no_track_reason 為空的案件
- 每件案輸出一個 JSON：含 case_id / 當事人 / 律師 / 接案同仁 / lawyer_notes / tracking_notes / has_line / 諮詢日距今天數
- 用法：
    python prepare_pending_prompts.py                  # 全部 197 件
    python prepare_pending_prompts.py --limit 5        # 樣本測試
    python prepare_pending_prompts.py --lawyer 雷皓明  # 只跑單一律師
- 輸出：/tmp/pending_prompts.jsonl
"""
import os, io, sys, json, argparse
from datetime import date, timedelta
import httpx
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv("/Users/dennislei/projects/lawyer-dashboard/scripts/.env")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

TODAY = date(2026, 5, 19)
CUTOFF = (TODAY - timedelta(days=30)).isoformat()
OUT_PATH = "/tmp/pending_prompts.jsonl"


def fetch_all(table, select, extra=None):
    rows, off, page = [], 0, 1000
    while True:
        params = {"select": select, "limit": str(page), "offset": str(off)}
        if extra:
            params.update(extra)
        r = httpx.get(f"{URL}/rest/v1/{table}", params=params, headers=HDR, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        off += page
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--lawyer", type=str, default=None)
    ap.add_argument("--out", type=str, default=OUT_PATH)
    args = ap.parse_args()

    lawyers = fetch_all("lawyers", "id,name")
    lmap = {l["id"]: l["name"] for l in lawyers}

    cases = fetch_all(
        "consultation_cases",
        "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,tracking_staff,tracking_notes,tracking_status,lawyer_notes,line_chat_url,no_track_reason,meeting_record",
        extra={"case_date": f"gte.{CUTOFF}", "is_signed": "eq.false"},
    )

    pending = [c for c in cases if not (c.get("no_track_reason") or "").strip()]
    if args.lawyer:
        pending = [c for c in pending if lmap.get(c["lawyer_id"], "") == args.lawyer]

    # 排序：諮詢日近的先
    pending.sort(key=lambda c: c["case_date"], reverse=True)

    if args.limit:
        pending = pending[: args.limit]

    out_rows = []
    for c in pending:
        days_ago = (TODAY - date.fromisoformat(c["case_date"])).days
        lawyer_notes = (c.get("lawyer_notes") or "").strip()
        tracking_notes = (c.get("tracking_notes") or "").strip()
        meeting_record = (c.get("meeting_record") or "").strip()
        line_url = (c.get("line_chat_url") or "").strip()

        out_rows.append({
            "case_id": c["id"],
            "case_date": c["case_date"],
            "days_ago": days_ago,
            "client_name": c.get("client_name") or "?",
            "case_type": c.get("case_type") or "",
            "lawyer_name": lmap.get(c["lawyer_id"], "?"),
            "tracking_staff": c.get("tracking_staff") or "",
            "tracking_status": c.get("tracking_status") or "",
            "lawyer_notes": lawyer_notes,
            "tracking_notes": tracking_notes,
            # meeting_record 只取前 800 字當參考（避免太長）
            "meeting_record_excerpt": meeting_record[:800] if meeting_record else "",
            "meeting_record_full_length": len(meeting_record),
            "line_chat_url": line_url,
            "data_sources": {
                "has_lawyer_notes": bool(lawyer_notes),
                "has_tracking_notes": bool(tracking_notes),
                "has_line_url": bool(line_url),
                "has_meeting_record": bool(meeting_record),
                "meeting_record_len": len(meeting_record),
                "line_msg_count": 0,  # 之後爬完更新
                "line_conversation": None,  # 之後爬完填入
            },
        })

    with open(args.out, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"已輸出 {len(out_rows)} 件 → {args.out}")
    if out_rows:
        print(f"  最新一件: {out_rows[0]['client_name']} ({out_rows[0]['days_ago']} 天前)")
        print(f"  最舊一件: {out_rows[-1]['client_name']} ({out_rows[-1]['days_ago']} 天前)")


if __name__ == "__main__":
    main()
