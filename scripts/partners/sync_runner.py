"""
sync_runner.py — partners dashboard 資料同步入口

流程：
  1. 跑 parse_judicial.py + parse_senior.py → CSVs
  2. 跑 build_embedded.py → dashboard.html（含 fresh embedded-data JSON）
  3. 抽出 <script id="embedded-data">…</script> 區塊
  4. 只替換 public/partners/index.html 的同一個區塊（其他 UI 程式碼不動）
  5. 印 diff summary（哪幾個律師-月份有變動）

使用方式：
  python sync_runner.py                  # 用預設路徑（Desktop 資料夾）跑
  python sync_runner.py --check          # 只 diff 不寫檔
  python sync_runner.py --commit         # diff 後自動 git commit + push
  python sync_runner.py --workdir <path> # 指定工作目錄（預設 = system temp）

環境變數（會 forward 給子腳本）：
  PARTNERS_JUDICIAL_INPUT_DIRS   ; 分隔多個（Windows 是 ;，Unix 是 :）
  PARTNERS_SENIOR_INPUT_DIRS
  PARTNERS_OUTPUT_DIR            ; CSV / dashboard.html 輸出位置

注意：律師月底才回填上月資料（4/29 填 3 月），daily cron 已足夠。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent  # lawyer-dashboard/
PARTNERS_HTML = REPO_ROOT / "public" / "partners" / "index.html"

EMBEDDED_RE = re.compile(
    r'(<script id="embedded-data" type="application/json">)(.*?)(</script>)',
    re.DOTALL,
)


def run_step(name: str, script: Path, env: dict) -> None:
    print(f"\n=== {name} ===")
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"step '{name}' failed (exit {result.returncode})")
    # Print last 6 lines of output for visibility
    tail = result.stdout.strip().split("\n")[-6:]
    for line in tail:
        print(f"  {line}")


def extract_embedded_json(html_path: Path) -> tuple[str, dict]:
    """讀 html_path 拿出 embedded-data 的 raw JSON 字串 + parsed dict。"""
    text = html_path.read_text(encoding="utf-8")
    m = EMBEDDED_RE.search(text)
    if not m:
        raise SystemExit(f"no <script id='embedded-data'> found in {html_path}")
    raw = m.group(2)
    return raw, json.loads(raw)


def diff_embedded(current: dict, fresh: dict) -> dict:
    """回傳 {cohort: [(lawyer, year, month, reason), ...]}"""
    report = {"judicial": [], "senior": []}
    for cohort in ["judicial", "senior"]:
        cur = {(r["lawyer"], str(r["year"]), str(r["month"])): r
               for r in current["cohorts"][cohort]["monthly"]}
        fre = {(r["lawyer"], str(r["year"]), str(r["month"])): r
               for r in fresh["cohorts"][cohort]["monthly"]}
        for key in sorted(set(cur) | set(fre)):
            if key not in cur:
                report[cohort].append((*key, "NEW"))
                continue
            if key not in fre:
                report[cohort].append((*key, "REMOVED"))
                continue
            c, f = cur[key], fre[key]
            for fld in ["commission_A", "self_A", "consult_a", "proc_D",
                        "zhelu_total", "lawyer_total"]:
                if abs(float(c.get(fld) or 0) - float(f.get(fld) or 0)) > 1.0:
                    report[cohort].append((*key, f"{fld} {c.get(fld)}→{f.get(fld)}"))
                    break
    return report


def replace_embedded_block(html_path: Path, fresh_json_raw: str) -> None:
    text = html_path.read_text(encoding="utf-8")
    new_text = EMBEDDED_RE.sub(
        lambda m: m.group(1) + fresh_json_raw + m.group(3),
        text,
        count=1,
    )
    if new_text == text:
        print("  (no change in HTML — embedded-data unchanged)")
        return
    html_path.write_text(new_text, encoding="utf-8")
    print(f"  ✓ updated {html_path.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只 diff 不寫檔")
    ap.add_argument("--commit", action="store_true", help="變動時 git commit + push")
    ap.add_argument("--workdir", help="工作目錄（CSV / dashboard.html 輸出）；預設 = temp")
    args = ap.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="partners_sync_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"Workdir: {workdir}")

    env = os.environ.copy()
    env["PARTNERS_OUTPUT_DIR"] = str(workdir)
    env["PYTHONIOENCODING"] = "utf-8"

    # Step 1-2: parse + build
    run_step("parse_judicial", SCRIPT_DIR / "parse_judicial.py", env)
    run_step("parse_senior",   SCRIPT_DIR / "parse_senior.py", env)
    run_step("build_embedded", SCRIPT_DIR / "build_embedded.py", env)

    # Step 3-4: extract + diff
    fresh_html = workdir / "dashboard.html"
    if not fresh_html.exists():
        raise SystemExit(f"build_embedded did not produce {fresh_html}")
    fresh_raw, fresh_json = extract_embedded_json(fresh_html)
    _, current_json = extract_embedded_json(PARTNERS_HTML)

    print("\n=== Diff vs current partners/index.html ===")
    report = diff_embedded(current_json, fresh_json)
    total = sum(len(v) for v in report.values())
    if total == 0:
        print("  (no changes)")
    else:
        for cohort, rows in report.items():
            if not rows:
                continue
            print(f"  {cohort}: {len(rows)} changes")
            for lawyer, y, m, why in rows[:20]:
                print(f"    {lawyer} {y}/{m}  {why}")

    # Step 5: replace
    if args.check:
        print("\n--check mode — not writing")
        return 0

    if total == 0:
        print("\nno changes to apply, exiting")
        if not args.workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        return 0

    print("\n=== Apply ===")
    replace_embedded_block(PARTNERS_HTML, fresh_raw)

    # Step 6: optional commit + push
    if args.commit:
        print("\n=== git commit + push ===")
        msg_lines = []
        for cohort, rows in report.items():
            if rows:
                months = sorted({(r[1], r[2]) for r in rows})
                ms = ", ".join(f"{y}/{m}" for y, m in months[:6])
                msg_lines.append(f"{cohort}: {ms}{'...' if len(months) > 6 else ''}")
        commit_msg = "sync(partners): refresh embedded-data\n\n" + "\n".join(msg_lines)
        subprocess.run(["git", "add", str(PARTNERS_HTML)], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=REPO_ROOT, check=True)
        print("  ✓ pushed to main")

    if not args.workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
