"""批次跑所有有會議記錄但未 LLM 分析的案件。

會自動：
1. 找出 DB 裡有 meeting_record/transcript 但 llm_analyzed_at IS NULL 的案件
2. 對每位律師依序跑 prep_1on1_data.py（若 prep 檔不存在）
3. 再跑 llm_analyze_cases.py
4. 印出進度與結果

用法：
  python llm_analyze_all_pending.py         # 正式執行
  python llm_analyze_all_pending.py --dry   # 只列出要跑哪些律師
"""
import httpx
import os
import io
import sys
import argparse
import subprocess
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCRIPTS_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPTS_DIR / ".env")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
RAW_DIR = SCRIPTS_DIR / "briefs" / "raw_data"


def fetch_pending():
    rows = []
    for off in range(0, 20000, 1000):
        h = {**H, "Range-Unit": "items", "Range": f"{off}-{off+999}"}
        r = httpx.get(
            f"{URL}/rest/v1/consultation_cases",
            params={
                "select": "lawyer_id,meeting_record,transcript,llm_analyzed_at",
                "or": "(meeting_record.not.is.null,transcript.not.is.null)",
            },
            headers=h,
            timeout=30,
        ).json()
        if not r:
            break
        rows.extend(r)
        if len(r) < 1000:
            break

    lawyers = httpx.get(f"{URL}/rest/v1/lawyers", params={"select": "id,name"}, headers=H).json()
    names = {l["id"]: l["name"] for l in lawyers}

    pending = defaultdict(int)
    for r in rows:
        lid = r.get("lawyer_id")
        if not lid:
            continue
        if not r.get("llm_analyzed_at"):
            pending[lid] += 1
    return [(names.get(lid, lid[:8]), cnt, lid) for lid, cnt in sorted(pending.items(), key=lambda x: -x[1])]


def run_cmd(cmd, label):
    print(f"\n  ▶ {label}")
    print(f"    cmd: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=SCRIPTS_DIR, capture_output=True, text=True, encoding="utf-8", timeout=1800)
        if proc.returncode != 0:
            print(f"    ✗ FAILED (exit {proc.returncode})")
            if proc.stderr:
                print("    stderr:", proc.stderr[-500:])
            return False
        # print tail of output
        if proc.stdout:
            tail = "\n".join(proc.stdout.strip().split("\n")[-10:])
            print("    ...", tail.replace("\n", "\n    "))
        return True
    except subprocess.TimeoutExpired:
        print("    ✗ TIMEOUT (30 min)")
        return False
    except Exception as e:
        print(f"    ✗ EXCEPTION: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    pending = fetch_pending()
    if not pending:
        print("沒有待分析案件 ✓")
        return

    total = sum(p[1] for p in pending)
    print(f"共 {len(pending)} 位律師待分析，合計 {total} 筆案件")
    for i, (name, cnt, _lid) in enumerate(pending, 1):
        print(f"  {i:>3}. {name:<10} {cnt:>3} 筆")

    if args.dry:
        print("\n(--dry mode，未執行)")
        return

    ok = 0
    fail = []
    for i, (name, cnt, _lid) in enumerate(pending, 1):
        print(f"\n{'='*60}\n[{i}/{len(pending)}] {name}（{cnt} 筆）\n{'='*60}")
        prep_path = RAW_DIR / f"{name}_prep.json"
        # Always re-run prep to pick up latest DB state
        if not run_cmd([sys.executable, "prep_1on1_data.py", "--name", name], f"prep {name}"):
            fail.append((name, "prep 失敗"))
            continue
        # Now analyze
        if not run_cmd([sys.executable, "llm_analyze_cases.py", "--name", name], f"analyze {name}"):
            fail.append((name, "analyze 失敗"))
            continue
        ok += 1

    print(f"\n{'='*60}")
    print(f"完成：{ok}/{len(pending)} 位律師成功")
    if fail:
        print(f"失敗 {len(fail)} 位：")
        for name, reason in fail:
            print(f"  {name}: {reason}")


if __name__ == "__main__":
    main()
