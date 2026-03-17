"""
import_cases.py
解析諮詢案件檔案，匯入 consultation_cases 表。

使用方式：
  python import_cases.py
  python import_cases.py --dir /path/to/consult_data/諮詢律師

檔案命名格式：
  律師名_成案/未成案_日期_案件類型(會議記錄/逐字稿).docx/.txt

環境變數（或 .env）：
  SUPABASE_URL=https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
"""

import argparse
import os
import re
import sys

# Windows 終端 UTF-8 輸出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pathlib import Path

import httpx
from dotenv import load_dotenv

# 嘗試載入 python-docx
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    print("警告: python-docx 未安裝，將跳過 .docx 檔案的內容讀取")

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
DEFAULT_DIR = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "/tmp")), "consult_data", "諮詢律師")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

# 檔名解析正規表達式
# 格式: 律師名_成案/未成案_日期_案件類型(會議記錄/會議紀錄/逐字稿).docx/.txt
# 注意：有些檔名的「未成案」和日期之間沒有底線
FILE_PATTERN = re.compile(
    r'^(.+?)_(成案|未成案)_?(\d{8})_?(.+?)\((會議記錄|會議紀錄|逐字稿)\)\.(docx|txt|pdf)(?:\s.*)?$'
)


def read_docx(path: str) -> str:
    """讀取 .docx 檔案內容。"""
    if not HAS_DOCX:
        return ""
    try:
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        print(f"  讀取 docx 失敗: {path} -> {e}")
        return ""


def read_txt(path: str) -> str:
    """讀取 .txt 檔案內容，嘗試多種編碼。"""
    for enc in ["utf-8", "utf-8-sig", "big5", "cp950", "gbk"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    print(f"  讀取 txt 失敗（編碼問題）: {path}")
    return ""


def read_file_content(path: str) -> str:
    """根據副檔名讀取檔案內容。"""
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        return read_txt(path)
    elif ext == ".docx":
        return read_docx(path)
    elif ext == ".pdf":
        print(f"  跳過 PDF 檔案: {path}")
        return ""
    return ""


def parse_filename(filename: str):
    """
    解析檔名，回傳 (律師名, is_signed, date_str, case_type, content_type) 或 None。
    content_type: '會議記錄' / '會議紀錄' / '逐字稿'
    """
    # 先處理「的副本」等後綴 — 在正規表達式中已處理
    m = FILE_PATTERN.match(filename)
    if not m:
        return None

    lawyer_name = m.group(1).strip()
    is_signed = m.group(2) == "成案"
    date_str = m.group(3)
    case_type = m.group(4).strip()
    content_type = m.group(5)

    return lawyer_name, is_signed, date_str, case_type, content_type


def get_lawyer_map(client: httpx.Client) -> dict:
    """取得律師名稱到 ID 的對應。"""
    resp = client.get(
        f"{SUPABASE_URL}/rest/v1/lawyers",
        params={"select": "id,name", "is_active": "eq.true"},
        headers={**HEADERS, "Prefer": ""},
    )
    resp.raise_for_status()
    lawyers = resp.json()
    return {l["name"]: l["id"] for l in lawyers}


def scan_files(directory: str) -> dict:
    """
    掃描目錄，回傳以 (律師名, date_str, case_type, is_signed) 為 key 的字典，
    value 為 { 'meeting_record': str, 'transcript': str }。
    """
    cases = {}
    dir_path = Path(directory)

    if not dir_path.exists():
        print(f"錯誤: 目錄不存在 -> {directory}")
        sys.exit(1)

    for f in sorted(dir_path.iterdir()):
        if f.is_dir():
            continue
        if f.suffix.lower() not in (".docx", ".txt", ".pdf"):
            continue

        parsed = parse_filename(f.name)
        if not parsed:
            print(f"  跳過（無法解析）: {f.name}")
            continue

        lawyer_name, is_signed, date_str, case_type, content_type = parsed
        key = (lawyer_name, date_str, case_type, is_signed)

        if key not in cases:
            cases[key] = {"meeting_record": "", "transcript": ""}

        content = read_file_content(str(f))

        if content_type in ("會議記錄", "會議紀錄"):
            cases[key]["meeting_record"] = content
        elif content_type == "逐字稿":
            cases[key]["transcript"] = content

    return cases


def upsert_cases(client: httpx.Client, cases: dict, lawyer_map: dict):
    """批次 upsert 案件資料到 Supabase。"""
    rows = []
    skipped_lawyers = set()

    for (lawyer_name, date_str, case_type, is_signed), content in cases.items():
        lawyer_id = lawyer_map.get(lawyer_name)
        if not lawyer_id:
            skipped_lawyers.add(lawyer_name)
            continue

        # 格式化日期: 20260225 -> 2026-02-25
        case_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        rows.append({
            "lawyer_id": lawyer_id,
            "case_date": case_date,
            "case_type": case_type,
            "is_signed": is_signed,
            "meeting_record": content["meeting_record"] or None,
            "transcript": content["transcript"] or None,
        })

    if skipped_lawyers:
        print(f"\n以下律師名稱在資料庫中找不到，已跳過:")
        for name in sorted(skipped_lawyers):
            print(f"  - {name}")

    if not rows:
        print("\n沒有可匯入的資料")
        return

    print(f"\n準備匯入 {len(rows)} 筆案件...")

    # 分批 upsert（每批 50 筆）
    batch_size = 50
    success = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        resp = client.post(
            f"{SUPABASE_URL}/rest/v1/consultation_cases",
            json=batch,
            headers=HEADERS,
        )
        if resp.status_code in (200, 201):
            success += len(batch)
            print(f"  已匯入 {success}/{len(rows)} 筆")
        else:
            print(f"  匯入失敗 (batch {i // batch_size + 1}): {resp.status_code}")
            print(f"  回應: {resp.text[:500]}")

    print(f"\n匯入完成: {success}/{len(rows)} 筆成功")


def main():
    parser = argparse.ArgumentParser(description="匯入諮詢案件資料到 Supabase")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="案件檔案目錄")
    parser.add_argument("--dry-run", action="store_true", help="只解析檔案，不匯入")
    args = parser.parse_args()

    print(f"掃描目錄: {args.dir}")
    cases = scan_files(args.dir)
    print(f"解析到 {len(cases)} 筆案件")

    if args.dry_run:
        print("\n[Dry Run] 解析結果:")
        for (name, date, ctype, signed), content in sorted(cases.items()):
            has_mr = "有" if content["meeting_record"] else "無"
            has_ts = "有" if content["transcript"] else "無"
            sign_label = "成案" if signed else "未成案"
            print(f"  {name} | {date} | {ctype} | {sign_label} | 會議記錄:{has_mr} | 逐字稿:{has_ts}")
        return

    with httpx.Client(timeout=60) as client:
        print("\n取得律師對應表...")
        lawyer_map = get_lawyer_map(client)
        print(f"  找到 {len(lawyer_map)} 位律師")

        upsert_cases(client, cases, lawyer_map)


if __name__ == "__main__":
    main()
