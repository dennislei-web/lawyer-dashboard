"""
清理 consultation_cases 裡 case_number 以 'UP_' 開頭的「假案件」。

這些是舊版 ZIP 上傳時由前端自動產生的 placeholder 案件，
會跟 CRM 爬蟲抓到的真案件並存，造成重複。

做法：
1. 撈所有 case_number LIKE 'UP_%' 的案件
2. 對每筆，在 consultation_cases 裡找同日（同律師）非 UP_ 開頭的真案件
   匹配順序：lawyer_id+case_date → case_type 模糊比對 → is_signed 收斂
3. 若找到唯一對應：把 meeting_record / transcript 搬過去（真案件若已有內容則跳過該欄）
4. 刪除 UP_ 假案件

預設 dry-run。加 --apply 才真正執行。
"""
import argparse, httpx, os, io, sys
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def fetch_all(path, params):
    """分頁撈全部。"""
    rows = []
    offset = 0
    page = 1000
    while True:
        p = dict(params)
        p["limit"] = str(page)
        p["offset"] = str(offset)
        r = httpx.get(f"{url}/rest/v1/{path}", params=p, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        rows.extend(data)
        if len(data) < page:
            break
        offset += page
    return rows


def find_match(fake, real_by_key):
    """在 real_by_key[(lawyer_id, case_date)] list 裡挑唯一對應的真案件"""
    candidates = real_by_key.get((fake["lawyer_id"], fake["case_date"]), [])
    if len(candidates) == 0:
        return None, "none"
    if len(candidates) == 1:
        return candidates[0], "one"

    # case_type 模糊比對
    ct = (fake.get("case_type") or "").strip()
    by_type = []
    for x in candidates:
        xt = (x.get("case_type") or "").strip()
        if ct and xt and (xt == ct or ct in xt or xt in ct):
            by_type.append(x)
    if len(by_type) == 1:
        return by_type[0], "one"

    # 再用 is_signed 收斂
    if len(by_type) > 1:
        by_sign = [x for x in by_type if x.get("is_signed") == fake.get("is_signed")]
        if len(by_sign) == 1:
            return by_sign[0], "one"
        return None, f"ambiguous({len(by_type)})"
    return None, f"ambiguous({len(candidates)})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="實際執行（預設 dry-run）")
    args = ap.parse_args()

    print("=" * 70)
    print(f"  Cleanup UP_ 假案件  ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 70)

    # 1. 撈所有 UP_ 開頭案件
    print("\n[1] 撈 case_number LIKE 'UP_%' 的假案件…")
    fakes = fetch_all("consultation_cases", {
        "select": "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected,meeting_record,transcript",
        "case_number": "like.UP_*",
        "order": "case_date.desc",
    })
    print(f"    共 {len(fakes)} 筆")

    if not fakes:
        print("\n✓ 沒有假案件需要清理。")
        return

    # 2. 撈這些案件可能對應的真案件：用 lawyer_id + case_date 範圍
    lawyer_ids = sorted({f["lawyer_id"] for f in fakes})
    dates = sorted({f["case_date"] for f in fakes})
    print(f"\n[2] 撈候選真案件（{len(lawyer_ids)} 位律師、{len(dates)} 個日期）…")
    # 撈那些律師在那些日期的所有 case（含 UP_）然後自行篩
    real_candidates = fetch_all("consultation_cases", {
        "select": "id,lawyer_id,case_date,case_type,case_number,is_signed,meeting_record,transcript",
        "lawyer_id": "in.(" + ",".join(lawyer_ids) + ")",
        "case_date": "in.(" + ",".join(dates) + ")",
    })
    reals = [x for x in real_candidates if not (x.get("case_number") or "").startswith("UP_")]
    print(f"    候選 {len(real_candidates)} 筆，真案件 {len(reals)} 筆")

    # 3. 以 (lawyer_id, case_date) 建索引
    real_by_key = {}
    for x in reals:
        real_by_key.setdefault((x["lawyer_id"], x["case_date"]), []).append(x)

    # 4. 撈律師名對應
    lawyers = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name"}, headers=headers).json()
    lname = {l["id"]: l["name"] for l in lawyers}

    # 5. 逐筆配對
    print("\n[3] 配對結果：")
    plan = {"move": [], "skip_no_match": [], "skip_ambiguous": [], "skip_empty": []}
    for f in fakes:
        has_mr = bool(f.get("meeting_record"))
        has_ts = bool(f.get("transcript"))
        if not has_mr and not has_ts:
            plan["skip_empty"].append(f)
            continue

        match, kind = find_match(f, real_by_key)
        if kind == "one":
            plan["move"].append((f, match))
        elif kind == "none":
            plan["skip_no_match"].append(f)
        else:
            plan["skip_ambiguous"].append((f, kind))

    print(f"\n  ✓ 可搬移：{len(plan['move'])} 筆")
    print(f"  ⏭ 本身無內容（直接刪）：{len(plan['skip_empty'])} 筆")
    print(f"  ⚠ CRM 無對應真案件：{len(plan['skip_no_match'])} 筆（保留、不動）")
    print(f"  ⚠ 同日多筆無法判斷：{len(plan['skip_ambiguous'])} 筆（保留、不動）")

    # 6. 列出前 20 筆要搬移的
    print(f"\n[4] 搬移計畫（顯示前 20 筆）：")
    for i, (fake, real) in enumerate(plan["move"][:20]):
        nm = lname.get(fake["lawyer_id"], "?")
        mr = "MR" if fake.get("meeting_record") else "  "
        ts = "TS" if fake.get("transcript") else "  "
        rmr = "MR" if real.get("meeting_record") else "  "
        rts = "TS" if real.get("transcript") else "  "
        print(f"  {i+1:>3}. {nm:<6} {fake['case_date']} {fake.get('case_type','')[:14]:<14} "
              f"[{mr} {ts}] → {real['case_number']} (真案件目前 [{rmr} {rts}])")
    if len(plan["move"]) > 20:
        print(f"       … 還有 {len(plan['move']) - 20} 筆")

    if plan["skip_no_match"]:
        print(f"\n[5] CRM 查無對應的假案件（前 10 筆，將保留）：")
        for f in plan["skip_no_match"][:10]:
            nm = lname.get(f["lawyer_id"], "?")
            print(f"    {nm:<6} {f['case_date']} {f.get('case_type','')[:20]}")

    if plan["skip_ambiguous"]:
        print(f"\n[6] 同日多筆無法判斷的假案件（前 10 筆，將保留）：")
        for f, kind in plan["skip_ambiguous"][:10]:
            nm = lname.get(f["lawyer_id"], "?")
            print(f"    {nm:<6} {f['case_date']} {f.get('case_type','')[:20]} [{kind}]")

    if not args.apply:
        print("\n" + "=" * 70)
        print("  這是 DRY-RUN。加 --apply 才會真正執行。")
        print("=" * 70)
        return

    # 7. 實際執行
    print("\n" + "=" * 70)
    print("  開始執行搬移 + 刪除…")
    print("=" * 70)

    patch_headers = dict(headers)
    patch_headers["Prefer"] = "return=minimal"

    moved = 0
    move_errors = 0
    for fake, real in plan["move"]:
        patch = {}
        if fake.get("meeting_record") and not real.get("meeting_record"):
            patch["meeting_record"] = fake["meeting_record"]
        if fake.get("transcript") and not real.get("transcript"):
            patch["transcript"] = fake["transcript"]
        if patch:
            r = httpx.patch(
                f"{url}/rest/v1/consultation_cases",
                params={"id": f"eq.{real['id']}"},
                json=patch,
                headers=patch_headers,
                timeout=30,
            )
            if r.status_code not in (200, 204):
                print(f"  ✗ 更新真案件 {real['case_number']} 失敗：{r.status_code} {r.text[:120]}")
                move_errors += 1
                continue
        moved += 1

    print(f"\n  ✓ 已將 {moved} 筆內容搬到真案件（失敗 {move_errors} 筆）")

    # 8. 刪除所有「可搬」和「本身無內容」的假案件（保留 no_match / ambiguous）
    to_delete_ids = [f["id"] for f, _ in plan["move"]] + [f["id"] for f in plan["skip_empty"]]
    print(f"\n  刪除 {len(to_delete_ids)} 筆 UP_ 假案件…")
    del_errors = 0
    # 一次刪一批（URL 長度考量）
    BATCH = 50
    for i in range(0, len(to_delete_ids), BATCH):
        batch_ids = to_delete_ids[i:i+BATCH]
        r = httpx.delete(
            f"{url}/rest/v1/consultation_cases",
            params={"id": "in.(" + ",".join(batch_ids) + ")"},
            headers=patch_headers,
            timeout=30,
        )
        if r.status_code not in (200, 204):
            print(f"  ✗ 刪除批次 {i} 失敗：{r.status_code} {r.text[:120]}")
            del_errors += len(batch_ids)
    print(f"  ✓ 刪除完成（失敗 {del_errors} 筆）")

    print("\n  保留未處理：")
    print(f"    CRM 查無對應：{len(plan['skip_no_match'])} 筆")
    print(f"    同日多筆無法判斷：{len(plan['skip_ambiguous'])} 筆")
    print("\n  （保留的案件請人工決定是否等 CRM 同步後再跑一次，或手動處理）")


if __name__ == "__main__":
    main()
