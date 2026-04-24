"""深入檢查剩下的 UP_ 案件 — 撈完整 meeting_record + 候選的 lawyer_notes + 候選的其他歷史 cases"""
import httpx, os, io, sys, re
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
u = os.environ["SUPABASE_URL"]
k = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": k, "Authorization": f"Bearer {k}"}


def fetch(path, **p):
    r = httpx.get(f"{u}/rest/v1/{path}", params=p, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


lname = {l["id"]: l["name"] for l in fetch("lawyers", select="id,name")}
ups = fetch("consultation_cases",
            select="id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
            case_number="like.UP_*",
            order="case_date.asc")

for i, up in enumerate(ups, 1):
    nm = lname.get(up["lawyer_id"], "?")
    mr = (up.get("meeting_record") or "")
    ts = (up.get("transcript") or "")

    # 撈同日候選的完整資訊（含 lawyer_notes / tracking_notes）
    reals = fetch("consultation_cases",
                  select="id,case_number,case_type,client_name,is_signed,revenue,collected,lawyer_notes,tracking_notes,tracking_status",
                  lawyer_id=f"eq.{up['lawyer_id']}",
                  case_date=f"eq.{up['case_date']}")
    reals = [x for x in reals if not (x.get("case_number") or "").startswith("UP_")]

    print("\n" + "=" * 90)
    print(f"[{i}/{len(ups)}]  {nm}  {up['case_date']}  UP:{up.get('case_type','')}  ({'成' if up.get('is_signed') else '未'})")

    # 印 MR 前 1500 字（更長，看細節）
    mr_snip = re.sub(r"\s+", " ", mr.strip())[:1500]
    print(f"\n  ── MR 前 1500 字 ──")
    print(f"  {mr_snip}")

    print(f"\n  ── 候選 CRM 案件（含 lawyer_notes / tracking）──")
    for j, r in enumerate(reals, 1):
        cn = r.get("client_name") or ""
        print(f"\n  {j}. {r['case_number']}  client={cn}  成案={'成' if r.get('is_signed') else '未'}  "
              f"應收={r.get('revenue',0)}  已收={r.get('collected',0)}")
        print(f"     case_type: {r.get('case_type','')}")
        ln_ = r.get("lawyer_notes") or ""
        tn_ = r.get("tracking_notes") or ""
        ts_ = r.get("tracking_status") or ""
        if ln_:
            print(f"     lawyer_notes: {re.sub(chr(10)+'|'+chr(13), ' ', ln_)[:400]}")
        if tn_ or ts_:
            print(f"     tracking: status={ts_}  notes={re.sub(chr(10)+'|'+chr(13), ' ', tn_)[:200]}")

        # 另撈該 client 的歷史 cases（看律師過去跟這位客戶處理什麼）
        # 先拿 case_number 的 substring 當作 client identifier — 實際要用 client_name
        hist = fetch("consultation_cases",
                     select="case_date,case_type,is_signed,lawyer_notes",
                     client_name=f"eq.{cn}",
                     order="case_date.desc",
                     limit="5") if cn else []
        other_cases = [h for h in hist if h.get("case_date") != up["case_date"]]
        if other_cases:
            print(f"     同 client 其他 cases（最多 5 筆）：")
            for h in other_cases[:5]:
                print(f"       {h['case_date']}  {h.get('case_type','')[:30]}  {'成' if h.get('is_signed') else '未'}")

    print()
