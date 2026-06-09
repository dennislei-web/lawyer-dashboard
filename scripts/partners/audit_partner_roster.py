#!/usr/bin/env python3
"""
audit_partner_roster.py — 用 partner_roster.json 當唯一名冊，檢查所有硬編碼點有沒有漏掉某位合署律師。

用途：新增合署律師 / 定期巡檢時跑。read-only，不改任何檔。
  python scripts/partners/audit_partner_roster.py

每個硬編碼點定義「該出現哪些律師」(predicate)，逐一檢查名字是否出現在該檔內容。
有缺漏會列出來並 exit 1（方便 CI / skill 驗收）。
"""
import json, os, sys, io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROSTER = os.path.join(os.path.dirname(__file__), "partner_roster.json")

def load_roster():
    with open(ROSTER, encoding="utf-8") as f:
        return json.load(f)["lawyers"]

def read(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()

# 每個 site: (檔案, 人類說明, predicate, excel_gated)
# excel_gated=True 的站點，excel_ready=false 的律師算「⏳ 待 Excel」而非硬缺漏。
def is_website_partner(l): return l["website_class"] in ("合夥", "顧問", "資深合署")
def is_any(l): return True
def is_firm_split(l): return l.get("firm_split") is True
def is_senior(l): return l["cohort"] == "senior"
def is_judicial(l): return l["cohort"] == "judicial"
def is_consult(l): return l["cohort"] == "consult"
def is_excel(l): return l.get("excel_profit_share") is True
def excel_ready(l): return l.get("excel_ready", True) is True

SITES = [
    ("public/revenue/index.html",                 "WEBSITE_PARTNERS / PARTNER_SINCE (合署分類+owner生效日)", is_website_partner, False),
    ("public/revenue/index.html",                 "PARTNER_SINCE (owner生效日, 全合署)",                    is_any,            False),
    ("scripts/build_case_cost_data.py",           "PARTNER_SINCE (成本分析, 全合署)",                       is_any,            False),
    ("scripts/build_lawyer_tenure.py",            "ALREADY_PARTNER (forecast 可轉池排除)",                 is_any,            False),
    ("scripts/backfill_partner_attribution.py",   "PARTNER_SINCE (firm_amount 生效日, 限抽成型)",          is_firm_split,     False),
    ("scripts/partners/drive_client.py",          "TARGET_LAWYERS (Drive 取分潤 Excel)",                  is_excel,          True),
    ("scripts/partners/parse_senior.py",          "SENIOR_LAWYERS (資深 Excel 解析)",                     is_senior,         True),
    ("scripts/partners/build_embedded.py",        "SENIOR_LAWYERS+SENIOR_COLORS (資深 cohort 儀表板)",    is_senior,         True),
    ("scripts/partners/build_embedded.py",        "JUDICIAL_LAWYERS+JUDICIAL_COLORS (司法官 cohort)",    is_judicial,       True),
    ("scripts/partners/build_embedded.py",        "CONSULT_LAWYERS (諮詢律師 cohort)",                    is_consult,        True),
    ("scripts/partners/parse_judicial.py",        "FILENAME_PATTERN (司法官 Excel 解析)",                 is_judicial,       True),
    ("scripts/partners/analyze_judicial_cross_referral.py", "JUDICIAL set (跨轉分析)",                    is_judicial,       True),
]

def main():
    roster = load_roster()
    print(f"名冊共 {len(roster)} 位合署相關人員\n")
    total_gaps = 0
    pending = 0
    for path, desc, pred, gated in SITES:
        content = read(path)
        expect = [l for l in roster if pred(l)]
        if content is None:
            print(f"⚠ 找不到檔案: {path} ({desc})")
            total_gaps += 1
            continue
        missing = [l["name"] for l in expect if l["name"] not in content and (not gated or excel_ready(l))]
        waiting = [l["name"] for l in expect if l["name"] not in content and gated and not excel_ready(l)]
        if missing:
            total_gaps += len(missing)
            print(f"❌ {path}")
            print(f"   {desc}")
            print(f"   缺漏 {len(missing)} 位: {', '.join(missing)}")
        elif waiting:
            pending += len(waiting)
            print(f"⏳ {path} — {desc}")
            print(f"   待分潤 Excel 上傳後才加: {', '.join(waiting)}")
        else:
            print(f"✅ {path} — {desc} ({len(expect)} 位齊)")
    # firm_split 律師要在 DB 有 partner_terms (提醒，非檔案檢查)
    fs = [l["name"] for l in roster if is_firm_split(l)]
    print(f"\nℹ️ firm_split=true 需在 DB lawyers.partner_terms 設定: {', '.join(fs)}")
    print(f"   (用 SELECT name FROM lawyers WHERE partner_terms IS NOT NULL 對照)")
    print(f"\n{'='*50}")
    if pending:
        print(f"⏳ {pending} 處待分潤 Excel 上傳後補 cohort 站點（非錯誤）。")
    if total_gaps:
        print(f"⚠ 共 {total_gaps} 處硬缺漏，請補齊後重跑。")
        sys.exit(1)
    print("✅ 主儀表板層與名冊一致（cohort 分潤站點待 Excel 者除外）。")

if __name__ == "__main__":
    main()
