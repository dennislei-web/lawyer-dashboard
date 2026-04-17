"""
互動式處理剩下的 UP_ 假案件（同日多筆無法判斷 + CRM 查無）。

對每個 UP_ 案件：
- 顯示它的 meeting_record 摘要
- 列出同日候選 CRM 真案件的資訊（client_name / case_type / is_signed / amount）
- 讓使用者輸入 1/2/... 選擇要合併到哪個真案件，或 s 跳過 / d 直接刪除 / q 離開

選擇後：
- 把 meeting_record / transcript 搬到真案件（若真案件該欄已有內容，會問要不要覆蓋）
- 刪除 UP_ 假案件
"""
import httpx, os, io, sys
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
load_dotenv(r"C:\projects\lawyer-dashboard\scripts\.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
patch_headers = dict(headers)
patch_headers["Prefer"] = "return=minimal"


def summarize(text, n=200):
    if not text:
        return "(空)"
    t = text.replace("\n", " ").replace("\r", " ").strip()
    t = " ".join(t.split())  # 合併多餘空白
    if len(t) <= n:
        return t
    return t[:n] + "…"


def fmt_money(n):
    try:
        return f"${int(n):,}" if n else "-"
    except Exception:
        return "-"


def fetch_lawyers():
    r = httpx.get(f"{url}/rest/v1/lawyers", params={"select": "id,name"}, headers=headers, timeout=30)
    r.raise_for_status()
    return {l["id"]: l["name"] for l in r.json()}


def fetch_up_cases():
    """撈所有 UP_ 開頭的假案件，按律師+日期排序"""
    r = httpx.get(
        f"{url}/rest/v1/consultation_cases",
        params={
            "select": "id,lawyer_id,case_date,case_type,case_number,client_name,is_signed,revenue,collected,meeting_record,transcript",
            "case_number": "like.UP_*",
            "order": "lawyer_id.asc,case_date.asc",
        },
        headers=headers,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def fetch_same_day_reals(lawyer_id, case_date):
    """撈同律師同日期的非 UP_ 真案件"""
    r = httpx.get(
        f"{url}/rest/v1/consultation_cases",
        params={
            "select": "id,case_number,case_type,client_name,is_signed,revenue,collected,meeting_record,transcript",
            "lawyer_id": f"eq.{lawyer_id}",
            "case_date": f"eq.{case_date}",
        },
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return [x for x in r.json() if not (x.get("case_number") or "").startswith("UP_")]


def patch_case(case_id, patch):
    r = httpx.patch(
        f"{url}/rest/v1/consultation_cases",
        params={"id": f"eq.{case_id}"},
        json=patch,
        headers=patch_headers,
        timeout=30,
    )
    return r.status_code in (200, 204), r.text[:200] if r.status_code not in (200, 204) else ""


def delete_case(case_id):
    r = httpx.delete(
        f"{url}/rest/v1/consultation_cases",
        params={"id": f"eq.{case_id}"},
        headers=patch_headers,
        timeout=30,
    )
    return r.status_code in (200, 204), r.text[:200] if r.status_code not in (200, 204) else ""


def prompt(msg, valid):
    while True:
        try:
            s = input(msg).strip().lower()
        except EOFError:
            return "q"
        if s in valid:
            return s
        print(f"  請輸入：{'/'.join(valid)}")


def main():
    print("=" * 70)
    print("  UP_ 假案件 — 互動式人工處理")
    print("=" * 70)

    lname = fetch_lawyers()
    ups = fetch_up_cases()
    print(f"\n剩下 {len(ups)} 筆 UP_ 假案件待處理\n")
    if not ups:
        print("✓ 沒有要處理的案件。")
        return

    print("操作鍵：")
    print("  數字 1/2/...  選擇要合併到的真案件（搬 meeting_record/transcript 後刪除 UP_）")
    print("  s            跳過（保留這筆 UP_ 不動）")
    print("  d            直接刪除這筆 UP_（放棄它的 meeting_record/transcript 內容）")
    print("  q            離開（剩下的不處理）")
    print()

    stats = {"moved": 0, "deleted": 0, "skipped": 0, "errors": 0}

    for idx, up in enumerate(ups, 1):
        nm = lname.get(up["lawyer_id"], "?")
        print("\n" + "─" * 70)
        print(f"[{idx}/{len(ups)}]  {nm}  {up['case_date']}  {up.get('case_type','')}")
        print(f"            簽約: {'成案' if up.get('is_signed') else '未成案'}")
        print(f"            UP_ case_number: {up['case_number']}")
        mr = up.get("meeting_record") or ""
        ts = up.get("transcript") or ""
        print(f"  會議記錄 ({len(mr)} 字)：{summarize(mr, 220)}")
        if ts:
            print(f"  逐字稿   ({len(ts)} 字)：{summarize(ts, 160)}")

        reals = fetch_same_day_reals(up["lawyer_id"], up["case_date"])
        print(f"\n  候選 CRM 真案件（同律師同日期，共 {len(reals)} 筆）：")
        if not reals:
            print("    (無候選 — CRM 該日無此律師案件)")
        for i, r in enumerate(reals, 1):
            has_mr = "MR" if r.get("meeting_record") else "  "
            has_ts = "TS" if r.get("transcript") else "  "
            print(f"    {i}. {r['case_number']}  {'成案' if r.get('is_signed') else '未成案':<4}  "
                  f"{(r.get('case_type') or '')[:20]:<20}  "
                  f"{(r.get('client_name') or '')[:10]:<10}  "
                  f"應收={fmt_money(r.get('revenue'))}  已收={fmt_money(r.get('collected'))}  "
                  f"[{has_mr} {has_ts}]")

        valid = {str(i) for i in range(1, len(reals) + 1)} | {"s", "d", "q"}
        ans = prompt("\n  選擇 > ", valid)

        if ans == "q":
            print("\n離開。")
            break
        if ans == "s":
            stats["skipped"] += 1
            continue
        if ans == "d":
            confirm = prompt(f"  確認刪除（放棄 {len(mr)+len(ts)} 字的內容）? [y/n] ", {"y", "n"})
            if confirm != "y":
                stats["skipped"] += 1
                continue
            ok, err = delete_case(up["id"])
            if ok:
                print("  ✓ 已刪除")
                stats["deleted"] += 1
            else:
                print(f"  ✗ 刪除失敗：{err}")
                stats["errors"] += 1
            continue

        # 數字：選擇要合併的真案件
        target = reals[int(ans) - 1]
        patch = {}
        # meeting_record
        if mr:
            if target.get("meeting_record"):
                c = prompt(f"  真案件已有會議記錄 ({len(target['meeting_record'])} 字)，要覆蓋? [y/n/s(skip field)] ",
                           {"y", "n", "s"})
                if c == "y":
                    patch["meeting_record"] = mr
                # n 或 s：不動該欄
            else:
                patch["meeting_record"] = mr
        # transcript
        if ts:
            if target.get("transcript"):
                c = prompt(f"  真案件已有逐字稿 ({len(target['transcript'])} 字)，要覆蓋? [y/n/s(skip field)] ",
                           {"y", "n", "s"})
                if c == "y":
                    patch["transcript"] = ts
            else:
                patch["transcript"] = ts

        if patch:
            ok, err = patch_case(target["id"], patch)
            if not ok:
                print(f"  ✗ 更新真案件失敗：{err}")
                stats["errors"] += 1
                continue
            fields = ", ".join(patch.keys())
            print(f"  ✓ 已把 {fields} 搬到 {target['case_number']}")

        ok, err = delete_case(up["id"])
        if ok:
            print(f"  ✓ 已刪除 UP_ 假案件")
            stats["moved"] += 1
        else:
            print(f"  ✗ 刪除 UP_ 失敗：{err}")
            stats["errors"] += 1

    print("\n" + "=" * 70)
    print("  統計")
    print("=" * 70)
    print(f"  合併搬移：{stats['moved']} 筆")
    print(f"  直接刪除：{stats['deleted']} 筆")
    print(f"  跳過保留：{stats['skipped']} 筆")
    print(f"  失敗：   {stats['errors']} 筆")


if __name__ == "__main__":
    main()
