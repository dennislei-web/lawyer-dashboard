"""Recompute 首委日 in public/partners/index.html embedded-data.

政策變更：首委任 = 同一律師下、同當事人、第一筆 amount > 2000 的付款日。
≤ 2000 的諮詢費不再被誤認為首委。

更新 cases[*] 與 repeat_entries[*] 的 first_date, days_since_first, classification；
也更新 repeat_config.rule_html 說明文案。
"""
import io, sys, re, json, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HTML_PATH = r"C:\projects\lawyer-dashboard\public\partners\index.html"
CONSULT_THRESHOLD = 2000  # amount ≤ 2000 視為諮詢費，不計為首委


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None


def recompute_cohort(cohort):
    cases = cohort.get("cases", [])
    # Step 1: per (lawyer, client), earliest date where amount > 2000
    first_map = {}
    for c in cases:
        if (c.get("amount") or 0) > CONSULT_THRESHOLD and c.get("date"):
            key = (c["lawyer"], c["client"])
            if key not in first_map or c["date"] < first_map[key]:
                first_map[key] = c["date"]

    # Step 2: update each case; mark exactly one entry per client as 首委
    # Sort cases by (lawyer, client, date, amount desc) so we can pick first engagement deterministically
    # On the first engagement day, pick the smallest amount > 2000 as 首委
    # (intuition: the initial/smaller installment is the "first" engagement).
    cases_sorted = sorted(
        enumerate(cases),
        key=lambda x: (
            x[1]["lawyer"],
            x[1]["client"],
            x[1].get("date") or "",
            x[1].get("amount") or 0,
        ),
    )
    first_marked = set()  # (lawyer, client) pairs already marked as 首委
    for _, c in cases_sorted:
        key = (c["lawyer"], c["client"])
        new_fd = first_map.get(key)
        amount = c.get("amount") or 0
        date = c.get("date") or ""

        if new_fd is None:
            c["first_date"] = None
            c["days_since_first"] = None
            c["classification"] = "諮詢"
            continue

        c["first_date"] = new_fd
        fd_d = parse_date(new_fd)
        d = parse_date(date)
        if d and fd_d:
            c["days_since_first"] = (d - fd_d).days
        else:
            c["days_since_first"] = None

        if amount <= CONSULT_THRESHOLD:
            c["classification"] = "諮詢"
        elif date == new_fd and key not in first_marked:
            c["classification"] = "首委"
            first_marked.add(key)
        elif c["days_since_first"] is not None and c["days_since_first"] <= 365:
            c["classification"] = "1年內續委"
        else:
            c["classification"] = "自案（首委>1年）"

    # Step 3: update repeat_entries using matching from cases
    # Match by (lawyer, client, year, month, case_amount) → copy fields
    case_lookup = {}
    for c in cases:
        key = (c["lawyer"], c["client"], str(c.get("year", "")), str(c.get("month", "")), c.get("amount"))
        case_lookup.setdefault(key, []).append(c)

    for e in cohort.get("repeat_entries", []):
        key = (e["lawyer"], e["client"], str(e.get("year", "")), str(e.get("month", "")), e.get("case_amount"))
        matches = case_lookup.get(key, [])
        if matches:
            c = matches[0]
            e["first_date"] = c["first_date"]
            e["days_since_first"] = c["days_since_first"]
            e["classification"] = c["classification"]
        else:
            # No exact match — fall back to per-(lawyer, client) lookup
            new_fd = first_map.get((e["lawyer"], e["client"]))
            e["first_date"] = new_fd
            amt = e.get("case_amount") or 0
            if new_fd is None:
                e["classification"] = "諮詢"
                e["days_since_first"] = None
            elif amt <= CONSULT_THRESHOLD:
                e["classification"] = "諮詢"
                # Approximate date as year-month-15
                e["days_since_first"] = None
            else:
                e["classification"] = "1年內續委"  # default; can't determine exact
                e["days_since_first"] = None


def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    m = re.search(r'(<script id="embedded-data"[^>]*>)(.+?)(</script>)', html, re.S)
    pre, json_str, post = m.group(1), m.group(2), m.group(3)
    data = json.loads(json_str)

    print("=" * 60)
    print("BEFORE")
    print("=" * 60)
    for cohort_name, cohort in data["cohorts"].items():
        from collections import Counter
        c_cnt = Counter(e["classification"] for e in cohort.get("repeat_entries", []))
        print(f"  {cohort_name} repeat_entries: {dict(c_cnt)}")

    for cohort_name, cohort in data["cohorts"].items():
        recompute_cohort(cohort)

    # Update rule_html text to match new policy
    new_rule_html = (
        "同一律師下同當事人，首次付款 > $2,000（排除諮詢費）的日期 = 首委日。之後：<br>"
        "‣ <strong style=\"color:var(--green)\">1 年內再委任</strong>（&le;365 天）= 喆律案，沿用 30% B 費 + E 分成<br>"
        "‣ <strong style=\"color:#b58bff\">自案（首委>1年）</strong>（&gt;365 天）= 律師自案，B = 0%、E 分成偏律師端<br>"
        "‣ <strong style=\"color:var(--fg-dim)\">諮詢</strong>（amount &le; $2,000）= 單純諮詢收費，不影響續委分類"
    )
    for cohort_name, cohort in data["cohorts"].items():
        rc = cohort.get("repeat_config")
        if rc:
            rc["rule_html"] = new_rule_html

    print()
    print("=" * 60)
    print("AFTER")
    print("=" * 60)
    for cohort_name, cohort in data["cohorts"].items():
        from collections import Counter
        c_cnt = Counter(e["classification"] for e in cohort.get("repeat_entries", []))
        print(f"  {cohort_name} repeat_entries: {dict(c_cnt)}")

    # Sample: check 吳珈緯
    wu = [e for e in data["cohorts"]["judicial"]["repeat_entries"] if e.get("client") == "吳珈緯"]
    print()
    print("sample — 吳珈緯:")
    for e in wu:
        print(f"  {e['year']}/{e['month']}: ${e['case_amount']} first={e['first_date']} days={e['days_since_first']} [{e['classification']}]")

    # Write back
    new_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html_out = html[: m.start()] + pre + new_json + post + html[m.end():]
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_out)
    print("\n已寫入", HTML_PATH)


if __name__ == "__main__":
    main()
