"""
drive_client.py — Drive API client，從共用資料夾下載合署律師案件明細 xlsx

認證方式（擇一）：
  - 環境變數 GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON：service account JSON 內容（GitHub Action 用）
  - 環境變數 GOOGLE_APPLICATION_CREDENTIALS：service account JSON 檔案路徑（本機用）

讀兩個 Drive 資料夾（遞迴含子夾），依檔名 regex 過濾出合署律師檔案：
  - 1f9h24a3C6X1HMYmUil4kEU_S9b3dgGiy  喆律 16【財務】（115+ 主夾）
  - 1Bf3QnFu4JxmDc5d971aL-er5kIHaSFAM  16【財務】/合署律師 子夾（114-）

對 Google Sheets 原生檔（.gsheet）會用 export API 轉成 .xlsx 下載。

CLI：
  python drive_client.py --dest C:\\path\\to\\dest_dir
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

# google-api-python-client / google-auth — 第一次跑會 import error，requirements.txt 已加
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ---------- 設定 ----------
FOLDER_115_PLUS = "1f9h24a3C6X1HMYmUil4kEU_S9b3dgGiy"  # 16【財務】(115+)
FOLDER_114_MINUS = "1Bf3QnFu4JxmDc5d971aL-er5kIHaSFAM"  # 16【財務】/合署律師 (114-)

# 11 位律師（4 司法官 + 7 資深）+ '孫' alias（孫少輔舊檔名）
TARGET_LAWYERS = [
    "方心瑜", "孫少輔", "許致維", "劉明潔",  # judicial
    "李昭萱", "林昀", "徐棠娜", "許煜婕", "陳璽仲", "蕭予馨", "吳柏慶",  # senior
    "孫",  # alias for 孫少輔（112/113 舊檔名）
]
FILENAME_RE = re.compile(
    r"(\d{3})年.*?(" + "|".join(TARGET_LAWYERS) + r")律師案件明細"
)

# Drive mimetypes
MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_GSHEET = "application/vnd.google-apps.spreadsheet"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


# ---------- 認證 ----------
def _get_credentials():
    raw = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        # diagnostic only：印 client_email shape，不印 private key 或 value 內容
        ce = info.get("client_email", "")
        if ce:
            print(f"  using service account: {ce[:30]}...{ce[-20:] if len(ce) > 50 else ''}")
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and Path(path).exists():
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit(
        "Drive credentials missing. Set either:\n"
        "  GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON  (raw JSON content; GitHub Action)\n"
        "  GOOGLE_APPLICATION_CREDENTIALS     (path to JSON file; local)"
    )


def build_service():
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


# ---------- 列檔（遞迴）----------
def _list_folder_recursive(service, folder_id: str, max_depth: int = 3, depth: int = 0) -> list[dict]:
    """遞迴列出 folder 下所有非資料夾檔案。"""
    if depth > max_depth:
        return []
    out: list[dict] = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files", []):
            if f["mimeType"] == MIME_FOLDER:
                out.extend(_list_folder_recursive(service, f["id"], max_depth, depth + 1))
            else:
                out.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


# ---------- 下載 ----------
def _download_to_path(service, request, dest: Path) -> None:
    fh = io.FileIO(str(dest), "wb")
    try:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    finally:
        fh.close()


def _download_xlsx(service, file_id: str, dest: Path) -> None:
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    _download_to_path(service, request, dest)


def _export_gsheet_to_xlsx(service, file_id: str, dest: Path) -> None:
    request = service.files().export_media(fileId=file_id, mimeType=MIME_XLSX)
    _download_to_path(service, request, dest)


# ---------- 主流程 ----------
def download_partners_files(dest_dir: Path, verbose: bool = True) -> list[Path]:
    """從兩個 Drive 資料夾把符合律師檔名 pattern 的檔下載 / 匯出成 xlsx 到 dest_dir。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    service = build_service()
    downloaded: list[Path] = []
    skipped = 0

    for folder_id, label in [(FOLDER_115_PLUS, "115+"), (FOLDER_114_MINUS, "114-")]:
        if verbose:
            print(f"  Listing {label} folder...")
        files = _list_folder_recursive(service, folder_id)
        if verbose:
            print(f"    {len(files)} files (incl subfolders)")

        for f in files:
            name = f["name"]
            stem = re.sub(r"\.(xlsx|gsheet)$", "", name, flags=re.IGNORECASE)
            if not FILENAME_RE.search(stem):
                skipped += 1
                continue
            # 跳過自動 Converted 副本（同檔內容兩份會讓 parser 混淆）
            if "(Converted -" in name or "Converted -" in name or "的副本" in name:
                if verbose:
                    print(f"    ⤳ skip (Converted/副本): {name}")
                skipped += 1
                continue

            # 統一存成 .xlsx
            local_name = re.sub(r"\.gsheet$", ".xlsx", name, flags=re.IGNORECASE)
            if not local_name.lower().endswith(".xlsx"):
                local_name += ".xlsx"

            dest = dest_dir / local_name
            if dest.exists():
                base = dest.stem
                ext = dest.suffix
                i = 2
                while (dest_dir / f"{base}_{i}{ext}").exists():
                    i += 1
                dest = dest_dir / f"{base}_{i}{ext}"

            try:
                if f["mimeType"] == MIME_GSHEET:
                    _export_gsheet_to_xlsx(service, f["id"], dest)
                    if verbose:
                        print(f"    ↓ exported gsheet  {name}")
                elif name.lower().endswith(".xlsx"):
                    _download_xlsx(service, f["id"], dest)
                    if verbose:
                        print(f"    ↓ downloaded xlsx  {name}")
                else:
                    # 不是 xlsx 也不是 gsheet（可能是 docx/PDF），跳過
                    if dest.exists():
                        dest.unlink()
                    continue
                downloaded.append(dest)
            except Exception as e:
                if verbose:
                    print(f"    ✗ failed: {name}  ({type(e).__name__})")
                if dest.exists():
                    try:
                        dest.unlink()
                    except OSError:
                        pass

    if verbose:
        print(f"\n  total: {len(downloaded)} downloaded, {skipped} skipped (no name match)")
    return downloaded


def main() -> int:
    import argparse
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="下載目的地資料夾")
    args = ap.parse_args()
    download_partners_files(Path(args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
