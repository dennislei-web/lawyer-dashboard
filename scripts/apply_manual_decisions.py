"""套用人工判斷後的 UP_ 假案件合併決策"""
import argparse, httpx, os, io, sys
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
MIN = dict(H)
MIN["Prefer"] = "return=minimal"


# 決策清單：(lawyer_name, case_date, case_type_substring_in_UP, action, target_case_number_or_None)
# action: "match" | "skip" | "delete"
DECISIONS = [
    # 無候選 or 無法判斷 → skip
    ("洪琬琪", "2026-01-24", "改定親權",       "skip", None),
    ("洪琬琪", "2026-01-24", "勞資爭議",        "skip", None),
    ("洪琬琪", "2026-01-28", "遺產繼承",        "skip", None),
    ("洪琬琪", "2026-03-26", "離婚協議書等",     "skip", None),
    ("洪琬琪", "2026-03-26", "刑事偵查",        "skip", None),
    ("洪琬琪", "2026-03-26", "婚姻中協議",      "skip", None),
    ("張又仁", "2026-01-06", "離婚等",          "delete", None),  # CRM 查無

    # 依 meeting_record 內容匹配
    ("洪琬琪", "2026-01-26", "回函",            "match", "1150120009"),   # 數遊網路科技
    ("洪琬琪", "2026-01-26", "離婚",            "match", "1150126005"),   # 江易霖（江先生）
    ("洪琬琪", "2026-02-05", "離婚協議書",       "match", "1150203017"),   # 范億歡（by elimination）
    ("洪琬琪", "2026-02-11", "妨害性自主",       "match", "1150209007"),   # 詹勳儒 (is_signed 未→未)
    ("洪琬琪", "2026-03-16", "離婚協議書",       "match", "1150309020"),   # 洪雅淳（by elimination）
    ("洪琬琪", "2026-03-19", "分管契約",         "match", "1150317009"),   # 高秀嬌+李明益（內容提到姊姊+李先生）
    ("洪琬琪", "2026-03-20", "侵害配偶權",       "match", "1150318009"),   # 楊茜伃（個人家事案 best guess）
    ("洪琬琪", "2026-03-20", "強制執行",         "match", "LA1150320001"), # 寶君貿易（公司強執 best guess）
    ("洪琬琪", "2026-03-21", "損害賠償",         "match", "1150323001"),   # 趙中愷（未→未）
    ("洪琬琪", "2026-03-27", "改定親權",         "match", "1150326015"),   # 江靚（未→未）
    ("劉奕靖", "2026-02-11", "離婚等",           "match", "1150211009"),   # 顏瑄霈（未→未）
    ("劉奕靖", "2026-02-13", "離婚等",           "match", "1150213015"),   # 洪詩棋（未→未，唯一未成案候選）
    ("劉奕靖", "2026-03-12", "離婚等",           "match", "1150309019"),   # 李後慶（未→未）
    ("劉奕靖", "2026-03-26", "詐欺",             "match", "1150326002"),   # 胡淳為（律師函+代協商 內容對應）
    ("劉奕靖", "2026-03-26", "業務侵占",         "match", "1150326002"),   # 同上
    ("劉奕靖", "2026-03-26", "酌定扶養費",       "match", "1150311002"),   # 楊承憲（家事扶養費）
    ("張又仁", "2026-03-31", "離婚等",           "match", "1150329006"),   # 高采婕（成→成）
]


def fetch(path, **p):
    r = httpx.get(f"{url}/rest/v1/{path}", params=p, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print(f"{'APPLY' if args.apply else 'DRY-RUN'}\n")

    lawyers = {l["name"]: l["id"] for l in fetch("lawyers", select="id,name")}

    # 撈所有 UP_ 案件
    ups = fetch("consultation_cases",
                select="id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
                case_number="like.UP_*")
    print(f"目前 UP_ 案件：{len(ups)} 筆\n")

    # 依 (lawyer_id, case_date, case_type 子字串) 聚類 UP_（處理重複）
    processed_ids = set()
    stats = {"match": 0, "delete": 0, "skip": 0, "err": 0, "not_found": 0}

    for (lname, ldate, substr, action, target_cn) in DECISIONS:
        lid = lawyers.get(lname)
        if not lid:
            print(f"  ✗ 找不到律師 {lname}")
            continue

        # 找出所有符合條件的 UP_ 案件
        candidates = [
            u for u in ups
            if u["lawyer_id"] == lid
            and u["case_date"] == ldate
            and substr in (u.get("case_type") or "")
            and u["id"] not in processed_ids
        ]

        if not candidates:
            print(f"  — 決策 {lname} {ldate} 「{substr}」 沒有未處理 UP_ 案件")
            continue

        # 撈真案件（目標）
        target = None
        if action == "match":
            reals = fetch("consultation_cases",
                          select="id,case_number,client_name,meeting_record,transcript",
                          lawyer_id=f"eq.{lid}",
                          case_date=f"eq.{ldate}")
            reals = [x for x in reals if x.get("case_number") == target_cn]
            if not reals:
                print(f"  ✗ 真案件 {target_cn} 不存在（{lname} {ldate}）")
                stats["not_found"] += 1
                continue
            target = reals[0]

        for u in candidates:
            processed_ids.add(u["id"])
            tag = f"{lname} {ldate} UP:{u.get('case_type','')[:16]}"

            if action == "skip":
                print(f"  · {tag}  → skip (保留)")
                stats["skip"] += 1
                continue

            if action == "delete":
                if args.apply:
                    r = httpx.delete(f"{url}/rest/v1/consultation_cases",
                                     params={"id": f"eq.{u['id']}"},
                                     headers=MIN, timeout=30)
                    ok = r.status_code in (200, 204)
                    print(f"  · {tag}  → DELETE {'✓' if ok else '✗'}")
                    stats["delete" if ok else "err"] += 1
                else:
                    print(f"  · {tag}  → DELETE (dry-run)")
                    stats["delete"] += 1
                continue

            if action == "match":
                patch = {}
                mr = u.get("meeting_record")
                ts = u.get("transcript")
                if mr and not target.get("meeting_record"):
                    patch["meeting_record"] = mr
                if ts and not target.get("transcript"):
                    patch["transcript"] = ts

                if args.apply:
                    if patch:
                        r = httpx.patch(f"{url}/rest/v1/consultation_cases",
                                        params={"id": f"eq.{target['id']}"},
                                        json=patch, headers=MIN, timeout=30)
                        if r.status_code not in (200, 204):
                            print(f"  ✗ {tag}  → patch 失敗：{r.text[:100]}")
                            stats["err"] += 1
                            continue
                        # 更新本地快取，避免重複搬
                        if "meeting_record" in patch: target["meeting_record"] = patch["meeting_record"]
                        if "transcript" in patch: target["transcript"] = patch["transcript"]
                    r = httpx.delete(f"{url}/rest/v1/consultation_cases",
                                     params={"id": f"eq.{u['id']}"},
                                     headers=MIN, timeout=30)
                    ok = r.status_code in (200, 204)
                    print(f"  ✓ {tag}  → {target_cn} ({target.get('client_name','')})  patch={list(patch.keys())}  del={'ok' if ok else 'err'}")
                    stats["match" if ok else "err"] += 1
                else:
                    print(f"  · {tag}  → {target_cn} ({target.get('client_name','')})  patch={list(patch.keys())}  (dry-run)")
                    stats["match"] += 1

    # 檢查未處理 UP_
    leftover = [u for u in ups if u["id"] not in processed_ids]
    print(f"\n統計：match={stats['match']} delete={stats['delete']} skip={stats['skip']} err={stats['err']} not_found={stats['not_found']}")
    print(f"未覆蓋到決策清單的 UP_：{len(leftover)} 筆")
    for u in leftover[:10]:
        print(f"  - {u['id'][:8]}  {u['case_date']} {u.get('case_type','')[:30]}")


if __name__ == "__main__":
    main()
