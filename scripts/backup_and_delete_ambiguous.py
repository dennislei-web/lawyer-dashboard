"""
把剩下的 UP_ 案件內容備份到 JSON 後刪除。
內容包含 meeting_record、transcript 與所有 metadata，供事後人工處理或追查。
"""
import argparse, json, httpx, os, io, sys
from datetime import datetime
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
u = os.environ["SUPABASE_URL"]
k = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}
MIN = dict(H); MIN["Prefer"] = "return=minimal"


def fetch(path, **p):
    r = httpx.get(f"{u}/rest/v1/{path}", params=p, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ups = fetch("consultation_cases",
                select="id,lawyer_id,case_date,case_type,case_number,is_signed,revenue,collected,meeting_record,transcript,created_at",
                case_number="like.UP_*",
                order="case_date.asc")
    print(f"剩餘 UP_：{len(ups)} 筆")

    if not ups:
        print("✓ 已無 UP_ 案件")
        return

    # 加上律師名稱方便查閱
    lname = {l["id"]: l["name"] for l in fetch("lawyers", select="id,name")}
    for up in ups:
        up["_lawyer_name"] = lname.get(up["lawyer_id"], "?")
        # 同日候選資訊也一併保存
        reals = fetch("consultation_cases",
                      select="case_number,client_name,case_type,is_signed",
                      lawyer_id=f"eq.{up['lawyer_id']}",
                      case_date=f"eq.{up['case_date']}")
        up["_same_day_crm_candidates"] = [x for x in reals if not (x.get("case_number") or "").startswith("UP_")]

    backup = {
        "backed_up_at": datetime.now().isoformat(),
        "count": len(ups),
        "note": "這些 UP_ 案件在 CRM 無法唯一對應，同日多筆候選無法自動判斷。若 CRM 後續補上對應案件，可依此備份手動把 meeting_record/transcript 貼回真案件。",
        "records": ups,
    }

    path = r"C:\projects\lawyer-dashboard\scripts\unmatched_uploads_backup.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"✓ 備份寫入：{path}  ({size_mb:.2f} MB)")

    print(f"\n備份內容摘要：")
    for up in ups:
        mr_len = len(up.get("meeting_record") or "")
        ts_len = len(up.get("transcript") or "")
        cands = ", ".join(f"{c['case_number']}({c.get('client_name','')})" for c in up["_same_day_crm_candidates"])
        print(f"  - {up['_lawyer_name']}  {up['case_date']}  {up.get('case_type','')[:25]}  "
              f"MR={mr_len}字 TS={ts_len}字  候選=[{cands}]")

    if not args.apply:
        print(f"\nDRY-RUN。備份已寫入檔案。加 --apply 才會刪除 DB 中的 UP_ 案件。")
        return

    # 執行刪除
    print(f"\n開始刪除…")
    ids = [u["id"] for u in ups]
    r = httpx.delete(
        f"{u}/rest/v1/consultation_cases",
        params={"id": "in.(" + ",".join(ids) + ")"},
        headers=MIN, timeout=30,
    )
    if r.status_code in (200, 204):
        print(f"✓ 已刪除 {len(ids)} 筆 UP_ 案件")
    else:
        print(f"✗ 刪除失敗：{r.status_code}  {r.text[:200]}")


if __name__ == "__main__":
    main()
