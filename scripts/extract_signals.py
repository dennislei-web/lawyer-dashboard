"""為剩下的 UP_ 案件抽取關鍵信號：當事人姓名、對造姓名、主要議題，方便人工判斷"""
import httpx, os, io, sys, re
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": key, "Authorization": f"Bearer {key}"}


def fetch(path, **p):
    r = httpx.get(f"{url}/rest/v1/{path}", params=p, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def extract_names(text):
    """從文字裡撈可能的人名（2-3 字中文姓名、先生/女士/律師 前面的字元）"""
    if not text:
        return set()
    names = set()
    # 「XX先生」「XX女士」「XX太太」「XX小姐」
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,3})(?=先生|女士|太太|小姐)", text[:3000]):
        names.add(m.group(1))
    # 「XX阿姨」「XX老師」「XX醫師」
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,3})(?=阿姨|老師|醫師)", text[:3000]):
        names.add(m.group(1))
    # 「被告XX」「告訴人XX」「對造XX」 — 常見的正式稱謂
    for m in re.finditer(r"(?:被告|告訴人|原告|對造|當事人)([\u4e00-\u9fa5]{2,3})", text[:3000]):
        names.add(m.group(1))
    return names


def first_section(text, n=800):
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text.strip())[:n]
    return t


lname = {l["id"]: l["name"] for l in fetch("lawyers", select="id,name")}
ups = fetch("consultation_cases",
            select="id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
            case_number="like.UP_*",
            order="lawyer_id.asc,case_date.asc")

print(f"剩 {len(ups)} 筆 UP_ 待處理\n")

for i, up in enumerate(ups, 1):
    nm = lname.get(up["lawyer_id"], "?")
    mr = (up.get("meeting_record") or "").strip()
    ts = (up.get("transcript") or "").strip()
    reals = fetch("consultation_cases",
                  select="id,case_number,case_type,client_name,is_signed,lawyer_notes",
                  lawyer_id=f"eq.{up['lawyer_id']}",
                  case_date=f"eq.{up['case_date']}")
    reals = [x for x in reals if not (x.get("case_number") or "").startswith("UP_")]

    # 從 mr+ts 抽姓名
    names_mr = extract_names(mr + "\n" + ts)

    # 檢查 CRM 候選 client_name 的組成字元是否出現在 mr/ts
    print(f"[{i:>2}/{len(ups)}]  {nm}  {up['case_date']}  UP:{up.get('case_type','')}  ({'成' if up.get('is_signed') else '未'})  id={up['id'][:8]}")
    print(f"     MR 前 400 字：{first_section(mr, 400)}")
    print(f"     抽到姓名：{list(names_mr) if names_mr else '無'}")
    print(f"     候選：")
    for r in reals:
        cn = r.get("client_name") or ""
        # 檢查每個 client_name 的每個字是否在 mr 前 3000 字
        sample = (mr + ts)[:3000]
        if cn:
            hits = {ch: sample.count(ch) for ch in cn if ch and not ch.isspace()}
        else:
            hits = {}
        print(f"        - {r['case_number']:<20}  {cn[:20]:<22}  {'成' if r.get('is_signed') else '未'}  "
              f"字元命中: {hits}")
    print()
