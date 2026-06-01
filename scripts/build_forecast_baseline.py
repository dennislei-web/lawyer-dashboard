#!/usr/bin/env python3
"""
五年營收獲利推估 — 歷史基線 ETL
產 public/forecast/forecast-baseline.json

內容：
  history: 各年（2021~2026）四流營收（毛, amount 口徑）、成本、諮詢量、案件動態
  wip_aging: 最新承辦存量帳齡分布
  defaults: 前端推估引擎的校準預設參數（成長率/成案率/成案金額/分潤留存率/結案天數…）

口徑（與 estimate_okr_profit.py / build_case_cost_data.py 對齊）：
  - revenue_records 用 amount（revenue 欄全 0），濾 is_void=false，Payment − Refund
  - 四流切分：合署(group_name 含「合署」) / 法顧(client_name ∈ advisor_clients) / 010(fact_010) / 本所(其餘)
  - 獲利採「總營收毛利」口徑：營收=毛收 amount；律師分潤 = 毛收 ×(1−留存率) 列為成本
  - 本所律師為固薪（成本在 personnel，留存率=1.0）；010/合署/法顧律師非固薪，留存率<1 反映分潤支出
  - 結案天數排除 ~1,400 件批次日(2023-02-08)汙染舊遷移案
  - finance fiscal_year 為民國年(114=2025)，月 1-12 對應西元同年月
"""
import os, sys, io, json, statistics
from collections import defaultdict, Counter
from datetime import datetime, date

import requests
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv('scripts/.env')
SB_URL = (os.environ.get('SUPABASE_URL') or 'https://zpbkeyhxyykbvownrngf.supabase.co').rstrip('/')
KEY = os.environ['SUPABASE_SERVICE_KEY']
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
LATEST_FULL_YEAR = 2025          # 最近一個完整年（base year）
BATCH_POLLUTION_DATE = date(2023, 2, 8)   # 舊遷移案批次更新日，非真實結案日
FA010_FIRM_SHARE_DEFAULT = 0.35  # 法0 喆律分得比例（estimate_okr_profit FA0_SHARE）

# ── 股東實際損益（營運數據(股東).xlsx，現金制 實際收入−實際支出，已排除合計欄）──
# 用來校準 OPEX（我的 bottom-up 成本低估）並畫真實歷史獲利線。2021-2025 為完整年（12月）。
# 喆律本所毛利率逐年崩：25.4%→15.4%→8.4%→3.1%→-0.0%；合併總盈虧含 010/公司/北冥。
ACTUAL_PNL_WAN = {   # 萬元
    2021: {'bensuo_profit': 2370, 'consolidated_profit': 1437, 'bensuo_rev': 9312},
    2022: {'bensuo_profit': 1852, 'consolidated_profit': 2860, 'bensuo_rev': 12016},
    2023: {'bensuo_profit': 1277, 'consolidated_profit': 2186, 'bensuo_rev': 15251},
    2024: {'bensuo_profit':  533, 'consolidated_profit': 2229, 'bensuo_rev': 17156},
    2025: {'bensuo_profit':   -3, 'consolidated_profit': 1416, 'bensuo_rev': 17197},
}


def fetch_all(table, params=None, page=1000):
    rows, offset = [], 0
    while True:
        p = dict(params or {}); p['limit'] = page; p['offset'] = offset
        for attempt in range(4):
            try:
                r = requests.get(f'{SB_URL}/rest/v1/{table}', headers=H, params=p, timeout=40)
                r.raise_for_status(); break
            except Exception as e:
                if attempt == 3: raise
        batch = r.json(); rows.extend(batch)
        if len(batch) < page: break
        offset += page
    return rows


def to_date(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace('Z', '+00:00')).date()
    except Exception: return None


def norm(s): return (s or '').strip()


# ════════ 1. 營收四流（revenue_records + fact_010 + partners JSON） ════════
print('[1/6] revenue_records 四流切分 ...')
# advisor 客戶集合（多年）
advisor_clients = set()
for r in fetch_all('advisor_cases', {'select': 'client_name'}):
    n = norm(r.get('client_name'));  advisor_clients.add(n) if n else None

rev_rows = fetch_all('revenue_records', {
    'select': 'record_date,amount,transaction_type,group_name,is_void,client_name',
    'is_void': 'eq.false',
})

bensuo_y = defaultdict(float)   # 本所委任（毛）
advisor_y = defaultdict(float)  # 法顧（毛, 來自 records）
partner_gross_y = defaultdict(float)  # 合署（毛, 客戶實付）
rev_months_2026 = set()         # 2026 已涵蓋月份（年化 YTD 用）
for r in rev_rows:
    rd = r.get('record_date')
    if not rd: continue
    yr = int(rd[:4])
    if yr not in YEARS: continue
    amt = float(r.get('amount') or 0)
    sign = 1 if r.get('transaction_type') == 'PaymentTransaction' else (-1 if r.get('transaction_type') == 'RefundTransaction' else 0)
    if sign == 0: continue
    amt *= sign
    if yr == 2026:
        rev_months_2026.add(int(rd[5:7]))
    grp = r.get('group_name') or ''
    cname = norm(r.get('client_name'))
    if '合署' in grp:
        partner_gross_y[yr] += amt
    elif cname in advisor_clients:
        advisor_y[yr] += amt
    else:
        bensuo_y[yr] += amt

# 010 平台（毛）
print('[2/6] fact_010_monthly_team ...')
fa010_y = defaultdict(float)
fa010_months_2026 = set()
for r in fetch_all('fact_010_monthly_team', {'select': 'year,month,total_revenue'}):
    yr = int(r['year'])
    if yr in YEARS:
        fa010_y[yr] += float(r.get('total_revenue') or 0)
        if yr == 2026:
            fa010_months_2026.add(int(r['month']))

# 合署留存率（喆律分得/毛）— 從 partners embedded JSON 校準
print('[3/6] partners JSON 合署留存率 ...')
partner_retain_default = 0.55
try:
    import re
    with open('public/partners/index.html', encoding='utf-8') as f:
        html = f.read()
    pj = json.loads(re.search(r'<script id="embedded-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1))
    g_gross = g_retain = 0.0
    for key in ('judicial', 'senior'):
        for rec in pj.get('cohorts', {}).get(key, {}).get('monthly', []):
            g_gross += float(rec.get('commission_A') or 0) + float(rec.get('self_A') or 0)
            g_retain += float(rec.get('zhelu_total') or 0)
    if g_gross > 0:
        partner_retain_default = round(g_retain / g_gross, 3)
    print(f'    合署毛收 {g_gross/1e4:,.0f}萬 / 喆律分得 {g_retain/1e4:,.0f}萬 → 留存率 {partner_retain_default:.1%}')
except Exception as e:
    print(f'    partners JSON 讀取失敗，用預設留存率 {partner_retain_default}: {e}')

# ════════ 4. 成本（人事 + OPEX） ════════
print('[4/6] finance 成本 ...')
fin_rows = fetch_all('finance_employees_monthly', {'select': 'fiscal_year,month,name,salary_subtotal'})
personnel_y = defaultdict(float)
headcount_names = defaultdict(set)
personnel_months = defaultdict(set)
for r in fin_rows:
    yr = int(r['fiscal_year']) + 1911
    if yr not in YEARS: continue
    personnel_y[yr] += float(r.get('salary_subtotal') or 0)
    nm = norm(r.get('name'))
    if nm: headcount_names[yr].add(nm)
    personnel_months[yr].add(int(r['month']))

# OPEX（非人事）— finance_data operating_expense, 用 actual 優先 fallback historical/budget
# 排除人事相關分類（薪資/退休金/職工福利），避免與 finance_employees_monthly 的 personnel 重複計
PERSONNEL_CATEGORIES = {'薪資費用', '薪資支出(年終預估)', '退休金', '職工福利'}
opex_y = defaultdict(float)
opex_months = defaultdict(set)
fd_rows = fetch_all('finance_data', {'select': 'amount,month,fiscal_year,data_type,finance_categories(name,section,is_subtotal)'})
_opex_by_ym = defaultdict(dict)  # (yr) -> {month: {data_type: amt}}
for r in fd_rows:
    cat = r.get('finance_categories') or {}
    if cat.get('section') != 'operating_expense' or cat.get('is_subtotal'): continue
    if cat.get('name') in PERSONNEL_CATEGORIES: continue
    yr = int(r['fiscal_year']) + 1911
    if yr not in YEARS: continue
    m = int(r.get('month') or 0)
    dt = r.get('data_type'); amt = float(r.get('amount') or 0)
    _opex_by_ym[yr].setdefault(m, defaultdict(float))[dt] += amt
for yr, months in _opex_by_ym.items():
    for m, by_type in months.items():
        amt = by_type.get('actual') or by_type.get('historical') or by_type.get('budget') or 0
        if amt:
            opex_y[yr] += amt; opex_months[yr].add(m)

# ════════ 5. 諮詢量 + 案件動態 ════════
print('[5/6] consult funnel + crm_cases ...')
sessions_y = defaultdict(float); leads_y = defaultdict(float)
for r in fetch_all('consult_oa_monthly_funnel', {'select': 'month_start,leads,sessions'}):
    d = to_date(r.get('month_start'))
    if d and d.year in YEARS:
        sessions_y[d.year] += float(r.get('sessions') or 0)
        leads_y[d.year] += float(r.get('leads') or 0)

case_rows = fetch_all('crm_cases', {'select': 'aasm_state,crm_created_at,appointed_at,closed_at,canceled_at'})
new_cases_y = defaultdict(int); closed_cases_y = defaultdict(int)
close_days_by_y = defaultdict(list)   # 結案天數（closed/canceled − appointed）
appointed_y = defaultdict(int)        # 成案數（appointed_at 年）
ACTIVE_STATES = {'appointed', 'pending'}
aging = {'<90': 0, '90-365': 0, '1-2yr': 0, '>2yr': 0}
today = date(2026, 6, 1)
for c in case_rows:
    cr = to_date(c.get('crm_created_at'))
    ap = to_date(c.get('appointed_at'))
    cl = to_date(c.get('closed_at')) or to_date(c.get('canceled_at'))
    if cr and cr.year in YEARS: new_cases_y[cr.year] += 1
    if ap and ap.year in YEARS: appointed_y[ap.year] += 1
    if cl and cl.year in YEARS and cl != BATCH_POLLUTION_DATE:
        closed_cases_y[cl.year] += 1
        if ap and cl >= ap:
            close_days_by_y[cl.year].append((cl - ap).days)
    # WIP 帳齡（最新承辦存量）
    if (c.get('aasm_state') in ACTIVE_STATES) and cr:
        age = (today - cr).days
        if age < 90: aging['<90'] += 1
        elif age < 365: aging['90-365'] += 1
        elif age < 730: aging['1-2yr'] += 1
        else: aging['>2yr'] += 1

# ════════ 6. 組裝 + 校準預設 ════════
print('[6/6] 組裝 + 校準預設參數 ...')


def series(d, cast=float):
    return [round(cast(d.get(y, 0)), 2) for y in YEARS]


def cagr(vals_by_year, y0, y1, clamp=(-0.30, 0.60)):
    a = vals_by_year.get(y0, 0); b = vals_by_year.get(y1, 0)
    if a <= 0 or b <= 0 or y1 <= y0: return 0.0
    g = (b / a) ** (1 / (y1 - y0)) - 1
    return round(max(clamp[0], min(clamp[1], g)), 4)


history = {
    'years': YEARS,
    'revenue_streams': {
        'bensuo':  series(bensuo_y),
        'fa010':   series(fa010_y),
        'advisor': series(advisor_y),
        'partner': series(partner_gross_y),
    },
    'cost': {
        'personnel':  series(personnel_y),
        'headcount':  [len(headcount_names.get(y, set())) for y in YEARS],
        'personnel_months': [len(personnel_months.get(y, set())) for y in YEARS],
        'opex':       series(opex_y),
        'opex_months': [len(opex_months.get(y, set())) for y in YEARS],
    },
    'consult': {'sessions': series(sessions_y), 'leads': series(leads_y)},
    'case_dynamics': {
        'new_cases':     [new_cases_y.get(y, 0) for y in YEARS],
        'appointed':     [appointed_y.get(y, 0) for y in YEARS],
        'closed_cases':  [closed_cases_y.get(y, 0) for y in YEARS],
        'close_days_median': [round(statistics.median(close_days_by_y[y]), 1) if close_days_by_y.get(y) else 0 for y in YEARS],
        'close_days_mean':   [round(statistics.mean(close_days_by_y[y]), 1) if close_days_by_y.get(y) else 0 for y in YEARS],
    },
}

# base year（最近完整年）run-rate
by = LATEST_FULL_YEAR
base = {
    'year': by,
    'bensuo':  round(bensuo_y.get(by, 0)),
    'fa010':   round(fa010_y.get(by, 0)),
    'advisor': round(advisor_y.get(by, 0)),
    'partner': round(partner_gross_y.get(by, 0)),
    'personnel': round(personnel_y.get(by, 0)),
    # OPEX base：年化最近有資料的年（歷史短）
    'opex': 0,
    'headcount': len(headcount_names.get(by, set())),
    'sessions': round(sessions_y.get(by, 0)),
    'appointed': appointed_y.get(by, 0),
}
# OPEX 年化：取覆蓋月數最完整的年（僅作參考，下面用實際損益校準）
opex_best_year = max((y for y in YEARS if opex_months.get(y)), key=lambda y: len(opex_months[y]), default=None)
opex_runrate = 0
if opex_best_year:
    m = len(opex_months[opex_best_year])
    opex_runrate = round(opex_y[opex_best_year] / m * 12) if m else 0

# ── OPEX 校準至股東實際損益 ──
# bottom-up(人事+finance OPEX) 嚴重低估真實成本（房租×6所/行銷/行政/獎金）。
# 反推 base year OPEX，使「2025 模型合併獲利 = 股東實際合併盈虧」。
#   profit = Σ毛收 − personnel − opex − 律師分潤  →  opex = Σ毛收 − personnel − 分潤 − 實際獲利
rev_2025 = bensuo_y.get(by,0)+fa010_y.get(by,0)+advisor_y.get(by,0)+partner_gross_y.get(by,0)
split_2025 = (fa010_y.get(by,0)*(1-FA010_FIRM_SHARE_DEFAULT)
              + advisor_y.get(by,0)*(1-0.85)
              + partner_gross_y.get(by,0)*(1-partner_retain_default))
actual_profit_2025 = ACTUAL_PNL_WAN[by]['consolidated_profit'] * 10000
opex_calibrated = round(rev_2025 - personnel_y.get(by,0) - split_2025 - actual_profit_2025)
base['opex'] = opex_calibrated
base['opex_runrate'] = opex_runrate
base['opex_source'] = f'校準至股東實際合併獲利{ACTUAL_PNL_WAN[by]["consolidated_profit"]}萬(finance OPEX 年化僅{round(opex_runrate/10000)}萬，低估真實房租/行銷/行政/獎金)'

# 真實歷史獲利線（合併總盈虧, 元）+ 本所實際盈虧
history['actual'] = {
    'consolidated_profit': [ACTUAL_PNL_WAN.get(y,{}).get('consolidated_profit',0)*10000 if y in ACTUAL_PNL_WAN else None for y in YEARS],
    'bensuo_profit':       [ACTUAL_PNL_WAN.get(y,{}).get('bensuo_profit',0)*10000 if y in ACTUAL_PNL_WAN else None for y in YEARS],
    'source': '營運數據(股東).xlsx 現金制 實際收入−實際支出',
}

# 2026 今年 YTD 年化 run-rate（推估起點錨定用）
rm = len(rev_months_2026); fm = len(fa010_months_2026)
run_rate_2026 = {
    'months_rev': rm, 'months_010': fm,
    'bensuo':  round(bensuo_y.get(2026, 0) / rm * 12) if rm else None,
    'advisor': round(advisor_y.get(2026, 0) / rm * 12) if rm else None,
    'partner': round(partner_gross_y.get(2026, 0) / rm * 12) if rm else None,
    'fa010':   round(fa010_y.get(2026, 0) / fm * 12) if fm else None,
}
base['run_rate_2026'] = run_rate_2026

# 漏斗校準：成案率 = appointed/sessions；平均成案金額 = 本所毛收/appointed
sess = base['sessions']; appt = base['appointed']
close_rate = round(appt / sess, 4) if sess else 0.0
avg_case_amount = round(base['bensuo'] / appt) if appt else 0

defaults = {
    'base': base,
    'salary_raise': 0.03,
    'retention': {        # 各流喆律留存率（毛收中留下的比例；本所固薪故=1.0）
        'bensuo': 1.0,
        'fa010': FA010_FIRM_SHARE_DEFAULT,
        'partner': partner_retain_default,
        'advisor': 0.85,
    },
    'growth': {           # 預設年成長率（成熟流用 CAGR；ramp 中/低信心流用保守固定值，皆 clamp）
        'bensuo':  cagr(bensuo_y, 2021, by),   # 成熟，CAGR 2021→base ≈ 15%
        'fa010':   cagr(fa010_y, 2022, by),    # 排除 2021 launch 半年，CAGR 2022→base
        'advisor': 0.20,                        # 低信心：歷史短，保守固定
        'partner': 0.25,                        # 低信心：仍在 ramp（2023 起），保守固定避免外推爆炸
        'opex':    0.03,
        'sessions': cagr(sessions_y, 2023, by),
    },
    'low_confidence': ['advisor', 'partner', 'opex'],
    'funnel': {
        'close_rate': close_rate,
        'avg_case_amount': avg_case_amount,
        'benefit_multiplier': 1.0,   # 效益值係數（續委任/客單放大）
        'sessions_growth': cagr(sessions_y, 2023, by),
    },
    'case_dynamics': {
        'close_days_base': history['case_dynamics']['close_days_median'][YEARS.index(by)],
        'close_days_yoy': 0.0,        # 結案天數逐年變化%（>0 = 拉長）
        'aging_haircut': 0.0,         # 老化庫存折減實現率%
    },
    'partner_conversion': {
        'tenure_threshold_years': 3,
        'convert_ratio': 0.80,
        'note': '需 lawyer-tenure.json（使用者到職日清單）才能精算達標律師；無清單時此區停用',
    },
}

output = {
    'meta': {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'asof': today.isoformat(),
        'base_year': by,
        'unit': 'TWD',
        'profit_basis': '總營收毛利（營收=毛收 amount；律師分潤=毛收×(1−留存率) 列成本）',
        'caveats': {
            'advisor': '法顧多年資料來自 revenue_records client 切分；advisor_transactions 僅 1 年',
            'partner': '合署毛收 2023 起，僅 2-3 有效年，成長率低信心',
            'opex': '非人事 OPEX 歷史僅近 1-2 年，base 為年化推估',
            'close_days': '已排除批次日 2023-02-08 汙染件；早年 appointed_at 覆蓋率低',
            'tenure': 'lawyers 表無到職日，合署轉換需另補 lawyer-tenure.json',
        },
    },
    'history': history,
    'wip_aging': aging,
    'defaults': defaults,
}

os.makedirs('public/forecast', exist_ok=True)
out_path = 'public/forecast/forecast-baseline.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, separators=(',', ':'))
with open('scripts/_forecast_preview.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# ════════ 摘要 ════════
wan = lambda v: f'{v/1e4:>10,.0f}萬'
print('\n══════ 歷史四流營收（毛, 萬元） ══════')
print('  年度    ' + '  '.join(f'{y:>8}' for y in YEARS))
for k, label in [('bensuo', '本所  '), ('fa010', '010   '), ('advisor', '法顧  '), ('partner', '合署  ')]:
    print(f'  {label}' + '  '.join(f'{v/1e4:>8,.0f}' for v in history['revenue_streams'][k]))
print('\n  人事成本' + '  '.join(f'{v/1e4:>8,.0f}' for v in history['cost']['personnel']))
print('  人數    ' + '  '.join(f'{v:>8}' for v in history['cost']['headcount']))
print('  人事月數' + '  '.join(f'{v:>8}' for v in history['cost']['personnel_months']))
print('  諮詢量  ' + '  '.join(f'{v:>8,.0f}' for v in history['consult']['sessions']))
print('  新案    ' + '  '.join(f'{v:>8}' for v in history['case_dynamics']['new_cases']))
print('  結案    ' + '  '.join(f'{v:>8}' for v in history['case_dynamics']['closed_cases']))
print('  結案天數' + '  '.join(f'{v:>8.0f}' for v in history['case_dynamics']['close_days_median']))
print(f'\n  base year {by}: 本所 {wan(base["bensuo"])} / 010 {wan(base["fa010"])} / 法顧 {wan(base["advisor"])} / 合署 {wan(base["partner"])}')
print(f'  人事 {wan(base["personnel"])} / OPEX(年化) {wan(base["opex"])} ({base.get("opex_source","")})')
print(f'  成案率 {close_rate:.1%} / 平均成案金額 {avg_case_amount/1e4:,.1f}萬 / 合署留存率 {partner_retain_default:.1%}')
print(f'  成長率預設: 本所 {defaults["growth"]["bensuo"]:.1%} / 010 {defaults["growth"]["fa010"]:.1%} / 法顧 {defaults["growth"]["advisor"]:.1%} / 合署 {defaults["growth"]["partner"]:.1%}')
print(f'  WIP 帳齡: {aging}')
print(f'\nsaved: {out_path}  ({os.path.getsize(out_path):,} bytes)')
