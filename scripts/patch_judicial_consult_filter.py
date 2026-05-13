"""
一次性 patch：對 public/partners/index.html 的 judicial cohort embedded JSON
重新跑「金額 > 2000 才算 承辦委任」的分類規則。

對齊 build_embedded.py 已修好的 judicial 邏輯（與 senior cohort 一致）：
- first_seen 只從 amount > 2000 的承辦案件算
- 每筆案件僅在 amount > 2000 時才分類
- repeat_entries 只收 classification != n/a 的案件

之後 sync 跑完會用 build_embedded.py 規則覆蓋，這個 patch 就不用再跑。
"""
from __future__ import annotations
import json, re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "public" / "partners" / "index.html"
EMBEDDED_RE = re.compile(
    r'(<script id="embedded-data" type="application/json">)(.*?)(</script>)',
    re.DOTALL,
)


def _parse_date(s):
    if not s: return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try: return datetime.strptime(str(s)[:10], fmt)
        except Exception: pass
    return None


def reclassify_judicial(j: dict) -> None:
    cases = j.get("cases", [])

    # first_seen 錨點只看金額 > 2000 的承辦紀錄（諮詢費不能當錨點）
    bucket = defaultdict(list)
    for c in cases:
        if c.get("section") != "承辦": continue
        amt = c.get("amount") or 0
        if amt <= 2000: continue
        d = _parse_date(c.get("date"))
        if d is None: continue
        client = (c.get("client") or "").strip()
        if not client: continue
        bucket[c["lawyer"]].append({"date": d, "client": client})

    first_seen = {}
    for l, items in bucket.items():
        items.sort(key=lambda x: x["date"])
        for it in items:
            key = (l, it["client"])
            if key not in first_seen:
                first_seen[key] = it["date"]

    # 同當事人若曾成立委任，所有紀錄（含拆帳的諮詢費）都納入分類
    for c in cases:
        d = _parse_date(c.get("date"))
        client = (c.get("client") or "").strip()
        c["classification"] = "n/a"
        c["days_since_first"] = None
        c["first_date"] = None
        if c.get("section") == "承辦" and d is not None and client:
            fs = first_seen.get((c["lawyer"], client))
            if fs is None:
                # 純諮詢當事人，整筆排除
                pass
            elif d <= fs:
                # 同一首委 episode（含拆出的諮詢費，可能早 1-3 天）
                c["classification"] = "首委"
                c["days_since_first"] = 0
                c["first_date"] = fs.strftime("%Y-%m-%d")
            else:
                days = (d - fs).days
                c["days_since_first"] = days
                c["first_date"] = fs.strftime("%Y-%m-%d")
                c["classification"] = "1年內續委" if days <= 365 else "1年外續委"

    # rebuild repeat_entries from re-classified cases
    new_entries = []
    for c in cases:
        if c.get("section") != "承辦": continue
        if c.get("classification") in (None, "n/a"): continue
        amt = c.get("amount") or 0
        cur_zhelu = amt * 0.30
        new_zhelu = 0.0 if c["classification"] == "1年外續委" else cur_zhelu
        new_entries.append({
            "lawyer": c["lawyer"], "year": c["year"], "month": c["month"],
            "tier": "承辦", "client": c["client"],
            "case_amount": amt,
            "cur_zhelu": cur_zhelu,
            "new_zhelu": new_zhelu,
            "classification": c["classification"],
            "days_since_first": c["days_since_first"],
            "first_date": c["first_date"],
            "source": c.get("source"),
        })
    j["repeat_entries"] = new_entries

    # CRM 已直接歸自案的續委（>1 年），供對帳用
    direct_self_renewals = []
    for c in cases:
        if c.get("section") != "自案": continue
        d = _parse_date(c.get("date"))
        if d is None: continue
        client = (c.get("client") or "").strip()
        if not client: continue
        fs = first_seen.get((c["lawyer"], client))
        if fs is None: continue
        days = (d - fs).days
        if days <= 365: continue
        direct_self_renewals.append({
            "lawyer": c["lawyer"], "year": c["year"], "month": c["month"],
            "client": client,
            "amount": c.get("amount") or 0,
            "date": c.get("date"),
            "first_date": fs.strftime("%Y-%m-%d"),
            "days_since_first": days,
            "source": c.get("source"),
        })
    direct_self_renewals.sort(key=lambda x: -x["amount"])
    j["direct_self_renewals"] = direct_self_renewals


def main() -> int:
    text = HTML_PATH.read_text(encoding="utf-8")
    m = EMBEDDED_RE.search(text)
    if not m:
        print("no <script id='embedded-data'> found")
        return 1
    data = json.loads(m.group(2))

    j = data["cohorts"]["judicial"]
    before = len(j["repeat_entries"])
    before_cur = sum(e["cur_zhelu"] for e in j["repeat_entries"])
    before_new = sum(e["new_zhelu"] for e in j["repeat_entries"])

    reclassify_judicial(j)

    after = len(j["repeat_entries"])
    after_cur = sum(e["cur_zhelu"] for e in j["repeat_entries"])
    after_new = sum(e["new_zhelu"] for e in j["repeat_entries"])
    print(f"judicial repeat_entries: {before} → {after}  (removed {before - after})")
    print(f"  cur_zhelu sum: ${before_cur:,.0f} → ${after_cur:,.0f}  (delta ${after_cur-before_cur:+,.0f})")
    print(f"  new_zhelu sum: ${before_new:,.0f} → ${after_new:,.0f}  (delta ${after_new-before_new:+,.0f})")

    # confirm 林麗敏 disappears
    lin = [e for e in j["repeat_entries"] if e.get("client") == "林麗敏"]
    print(f"  林麗敏 entries remaining: {len(lin)}")
    # report direct_self_renewals
    print(f"  direct_self_renewals: {len(j.get('direct_self_renewals', []))} 筆")

    new_json = json.dumps(data, ensure_ascii=False)
    new_text = EMBEDDED_RE.sub(lambda mm: mm.group(1) + new_json + mm.group(3), text, count=1)
    if new_text == text:
        print("no change")
        return 0
    HTML_PATH.write_text(new_text, encoding="utf-8")
    print(f"[OK] wrote {HTML_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
