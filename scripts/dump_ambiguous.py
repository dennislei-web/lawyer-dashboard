"""列出剩下的 UP_ 案件，每筆顯示 meeting_record 前 600 字 + 同日候選"""
import httpx, os, io, sys, re
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": key, "Authorization": f"Bearer {key}"}


def fetch(path, **params):
    r = httpx.get(f"{url}/rest/v1/{path}", params=params, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


lname = {l["id"]: l["name"] for l in fetch("lawyers", select="id,name")}
ups = fetch("consultation_cases",
            select="id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
            case_number="like.UP_*",
            order="lawyer_id.asc,case_date.asc")

print(f"剩 {len(ups)} 筆 UP_ 案件\n")

for i, up in enumerate(ups, 1):
    nm = lname.get(up["lawyer_id"], "?")
    mr = (up.get("meeting_record") or "").strip()
    ts = (up.get("transcript") or "").strip()
    reals = fetch("consultation_cases",
                  select="id,case_number,case_type,client_name,is_signed",
                  lawyer_id=f"eq.{up['lawyer_id']}",
                  case_date=f"eq.{up['case_date']}")
    reals = [x for x in reals if not (x.get("case_number") or "").startswith("UP_")]

    print("=" * 80)
    print(f"[{i}/{len(ups)}]  {nm}  {up['case_date']}  UP_type={up.get('case_type','')}  ({'成案' if up.get('is_signed') else '未成案'})")
    print(f"  id={up['id']}")
    print(f"\n  候選真案件：")
    for j, r in enumerate(reals, 1):
        print(f"    {j}. {r['case_number']:<28}  {(r.get('client_name') or '')[:18]:<20}  "
              f"{(r.get('case_type') or '')[:30]:<30}  {'成案' if r.get('is_signed') else '未成案'}")

    # 印會議記錄前 800 字
    print(f"\n  會議記錄（{len(mr)} 字，前 800 字）：")
    snippet = re.sub(r"\s+", " ", mr[:800])
    print(f"    {snippet}")
    if ts:
        print(f"\n  逐字稿（{len(ts)} 字，前 300 字）：")
        snippet2 = re.sub(r"\s+", " ", ts[:300])
        print(f"    {snippet2}")
    print()
