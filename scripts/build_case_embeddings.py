"""
把 consultation_cases 的 meeting_record / transcript / llm_analysis 切 chunk + embed，
upsert 到 case_chunks。

執行：
  python build_case_embeddings.py --dry-run           # 乾跑一筆看 chunk 結果（不寫 DB）
  python build_case_embeddings.py --limit 3 --dry-run # 乾跑 3 筆
  python build_case_embeddings.py                     # 增量 backfill（只處理新/改過的案件）
  python build_case_embeddings.py --rebuild           # 砍掉重建全部
  python build_case_embeddings.py --case-id <uuid>    # 單一案件

Embedding provider: Voyage AI voyage-law-2 (1024 dim)
"""
import os
import io
import sys
import json
import argparse
from pathlib import Path
import httpx
import tiktoken
import voyageai
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env", override=True)

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
VOYAGE_KEY = os.environ["VOYAGE_API_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
HDR_WRITE = {**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"}

vo = voyageai.Client(api_key=VOYAGE_KEY)
ENC = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
EMBED_MODEL = "voyage-law-2"
EMBED_BATCH = 32


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按 token 切，中英文都穩。回傳 list of {content, token_count}。"""
    if not text:
        return []
    tokens = ENC.encode(text)
    out = []
    i = 0
    while i < len(tokens):
        piece = tokens[i : i + size]
        out.append({"content": ENC.decode(piece), "token_count": len(piece)})
        if i + size >= len(tokens):
            break
        i += size - overlap
    return out


def extract_llm_chunks(llm_analysis):
    """從 llm_analysis JSON 抽各面向分析為獨立 chunk。

    llm_analyze_cases.py 的 schema：
      - strengths: list[str]            → llm_strength
      - failure_reason: str             ┐
      - reason_evidence: str            ┴→ llm_failure_reason (合併成一塊)
      - missed_opportunities: list[str] → llm_missed_opp
      - improvement_for_lawyer: str     → llm_improvement
      - transferable_pattern: str       → llm_pattern
    """
    if not llm_analysis:
        return []
    if isinstance(llm_analysis, str):
        try:
            llm_analysis = json.loads(llm_analysis)
        except Exception:
            return []

    out = []

    def add_chunk(source_type, content):
        content = (content or "").strip()
        if not content:
            return
        tokens = ENC.encode(content)
        out.append({
            "source_type": source_type,
            "chunk_index": 0,
            "content": content,
            "token_count": len(tokens),
        })

    # strengths: list → joined text
    strengths = llm_analysis.get("strengths")
    if isinstance(strengths, list) and strengths:
        add_chunk("llm_strength", "律師做得好的地方：\n" + "\n".join(f"- {s}" for s in strengths if s))
    elif isinstance(strengths, str):
        add_chunk("llm_strength", f"律師做得好的地方：{strengths}")

    # failure_reason + reason_evidence 合併（分類 + 實證一起檢索更有用）
    fr = llm_analysis.get("failure_reason")
    ev = llm_analysis.get("reason_evidence")
    if fr and fr != "已簽約":
        parts = [f"未成案原因：{fr}"]
        if ev:
            parts.append(f"會議記錄原文證據：{ev}")
        add_chunk("llm_failure_reason", "\n".join(parts))

    # missed_opportunities: list
    missed = llm_analysis.get("missed_opportunities")
    if isinstance(missed, list) and missed:
        add_chunk("llm_missed_opp", "律師錯過的關鍵轉機：\n" + "\n".join(f"- {m}" for m in missed if m))

    # improvement_for_lawyer: str
    imp = llm_analysis.get("improvement_for_lawyer")
    if imp:
        add_chunk("llm_improvement", f"給律師的改進建議：{imp}")

    # transferable_pattern: str
    pat = llm_analysis.get("transferable_pattern")
    if pat:
        add_chunk("llm_pattern", f"可轉移教訓：{pat}")

    return out


def prepare_chunks_for_case(case):
    """單一 case 的所有 chunk（帶 source_type + chunk_index）。"""
    all_chunks = []
    for field, source_type in [("meeting_record", "meeting_record"), ("transcript", "transcript")]:
        text = case.get(field)
        if not text:
            continue
        for idx, ch in enumerate(chunk_text(text)):
            all_chunks.append({
                "source_type": source_type,
                "chunk_index": idx,
                "content": ch["content"],
                "token_count": ch["token_count"],
            })
    all_chunks.extend(extract_llm_chunks(case.get("llm_analysis")))
    return all_chunks


def embed_batch(texts):
    """Voyage batch embed（input_type=document，語料用）。"""
    resp = vo.embed(texts=texts, model=EMBED_MODEL, input_type="document")
    return resp.embeddings


def _has_column(table, column):
    """偵測欄位是否存在（透過 OPTIONS/select 試打）。"""
    r = httpx.get(
        f"{URL}/rest/v1/{table}",
        params={"select": column, "limit": "1"},
        headers=HDR,
        timeout=30,
    )
    return r.status_code == 200


def fetch_cases(rebuild=False, case_id=None, limit=None):
    """抓需要 embed 的案件。

    - dry-run / limit / case-id 模式：case_date desc 排序，不需 updated_at
    - 增量模式（rebuild=False 且無 case_id/limit）：需 updated_at 欄位（由 20260422 migration 加上）
    """
    has_updated_at = _has_column("consultation_cases", "updated_at")
    select_cols = "id,case_date,case_type,client_name,lawyer_id,meeting_record,transcript,llm_analysis"
    if has_updated_at:
        select_cols += ",updated_at"

    params = {
        "select": select_cols,
        "meeting_record": "not.is.null",
        "order": "case_date.desc",  # dry-run / limit / single-case 都用 case_date 就好
    }
    if case_id:
        params["id"] = f"eq.{case_id}"
    if limit:
        params["limit"] = str(limit)

    r = httpx.get(f"{URL}/rest/v1/consultation_cases", params=params, headers=HDR, timeout=60)
    r.raise_for_status()
    cases = r.json()

    if rebuild or case_id or limit:
        return cases

    # 增量模式：必需 updated_at
    if not has_updated_at:
        print("[warn] consultation_cases.updated_at 欄位不存在，無法做增量判斷。", file=sys.stderr)
        print("       請先套 20260422000000_qa_schema.sql migration，或用 --rebuild / --limit / --case-id 模式。", file=sys.stderr)
        sys.exit(2)

    r2 = httpx.get(
        f"{URL}/rest/v1/case_chunks",
        params={"select": "case_id,created_at", "limit": "100000"},
        headers=HDR,
        timeout=60,
    )
    r2.raise_for_status()
    latest_chunk = {}
    for row in r2.json():
        cid = row["case_id"]
        if cid not in latest_chunk or row["created_at"] > latest_chunk[cid]:
            latest_chunk[cid] = row["created_at"]

    return [
        c for c in cases
        if c["id"] not in latest_chunk
        or (c.get("updated_at") or "") > latest_chunk[c["id"]]
    ]


def upsert_chunks(case_id, chunks_with_emb):
    """砍掉該案件所有 chunk 再寫新的（避免 stale）。"""
    httpx.delete(
        f"{URL}/rest/v1/case_chunks",
        params={"case_id": f"eq.{case_id}"},
        headers=HDR_WRITE,
        timeout=60,
    )
    if not chunks_with_emb:
        return
    rows = [{"case_id": case_id, **c} for c in chunks_with_emb]
    r = httpx.post(f"{URL}/rest/v1/case_chunks", headers=HDR_WRITE, json=rows, timeout=120)
    r.raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="砍掉重建全部")
    ap.add_argument("--case-id", help="單一案件 UUID")
    ap.add_argument("--limit", type=int, help="只處理前 N 筆")
    ap.add_argument("--dry-run", action="store_true", help="只印 chunk 結果，不呼叫 API、不寫 DB")
    args = ap.parse_args()

    cases = fetch_cases(rebuild=args.rebuild, case_id=args.case_id, limit=args.limit)
    print(f"待處理 {len(cases)} 筆案件\n")

    total_tokens = 0
    for i, case in enumerate(cases, 1):
        chunks = prepare_chunks_for_case(case)
        label = f'{case.get("client_name","?")} · {case.get("case_date","?")} · {case.get("case_type","?")}'

        if not chunks:
            print(f"[{i}/{len(cases)}] {label}: 無內容，跳過")
            continue

        token_sum = sum(c["token_count"] for c in chunks)
        total_tokens += token_sum

        if args.dry_run:
            print(f"[{i}/{len(cases)}] {label}: {len(chunks)} chunks / {token_sum} tokens")
            for c in chunks:
                preview = c["content"][:80].replace("\n", " ")
                print(f"  · {c['source_type']}#{c['chunk_index']} ({c['token_count']}tok): {preview}...")
            print()
            continue

        # 實際呼叫 Voyage + 寫 DB
        texts = [c["content"] for c in chunks]
        embeddings = []
        for j in range(0, len(texts), EMBED_BATCH):
            embeddings.extend(embed_batch(texts[j : j + EMBED_BATCH]))
        for c, e in zip(chunks, embeddings):
            c["embedding"] = e
        upsert_chunks(case["id"], chunks)
        print(f"[{i}/{len(cases)}] {label}: {len(chunks)} chunks / {token_sum} tokens ✓")

    cost = total_tokens / 1_000_000 * 0.12  # voyage-law-2 定價
    mode = "(dry-run，未呼叫 API)" if args.dry_run else ""
    print(f"\n完成 {mode}")
    print(f"總 tokens: {total_tokens:,}")
    print(f"估計成本（付費時）: ${cost:.4f}")
    print(f"Voyage 免費額度內大概都是 $0。")


if __name__ == "__main__":
    main()
