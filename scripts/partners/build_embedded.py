"""
讀 profit_share.csv + cases.csv + monthly_totals.csv（司法官合署 4 位）
 及 senior_*.csv（資深轉合署 7 位），聚合後塞進 dashboard.html template，
產出自足 HTML（可 file:// 直接開，不需伺服器）。
"""
import csv, json, os, sys, io
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

OUT = Path(os.environ.get('PARTNERS_OUTPUT_DIR') or r'C:\Users\admin\Desktop\新增資料夾\合署律師分析_output')

def num(x):
    if x is None or x == '' or x == 'None': return 0.0
    try: return float(x)
    except: return 0.0

def _parse_date(s):
    if not s: return None
    try: return datetime.strptime(str(s)[:10], '%Y-%m-%d')
    except: return None

# ============================================================
# Cohort 1: 司法官合署（4 位，現有管線）
# ============================================================
JUDICIAL_LAWYERS = ['劉明潔', '方心瑜', '孫少輔', '許致維']
JUDICIAL_COLORS = {'劉明潔': '#5dd39e', '方心瑜': '#f2b84b', '孫少輔': '#6aa9ff', '許致維': '#ff6b6b'}
JUDICIAL_TIERS = ['諮詢', '委任', '自案', '介紹', '追溯', '受僱', '續委', '轉案', '合作', '其他']

def build_judicial_cohort():
    with open(OUT / 'profit_share.csv', encoding='utf-8-sig') as f:
        profit = list(csv.DictReader(f))
    with open(OUT / 'cases.csv', encoding='utf-8-sig') as f:
        cases = list(csv.DictReader(f))
    with open(OUT / 'monthly_totals.csv', encoding='utf-8-sig') as f:
        totals = list(csv.DictReader(f))

    LAWYERS = JUDICIAL_LAWYERS

    # contract matrix
    pct_rows = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in profit:
        lawyer, year, tier = r['lawyer'], r['year'], r['tier']
        z, l = r.get('zhelu_pct', ''), r.get('lawyer_pct', '')
        if z == '' or l == '': continue
        pct_rows[lawyer][tier][(z, l)] += 1
    contract_matrix = {}
    for lawyer in LAWYERS:
        contract_matrix[lawyer] = {}
        for tier, pcts in pct_rows[lawyer].items():
            top = max(pcts.items(), key=lambda kv: kv[1])
            z, l = top[0]
            contract_matrix[lawyer][tier] = f'{float(z):.0f}/{float(l):.0f}'

    # monthly aggregate
    #   proc_D：委任費扣除 B/C/E 後的處理費（人事、交通、閱卷等共擔成本）
    #   這是司法官合署獨有 — 資深律師合約沒有這筆共擔成本
    monthly = {l: defaultdict(lambda: defaultdict(lambda: {
        'commission_A': 0, 'self_A': 0, 'consult_a': 0, 'proc_D': 0,
        'zhelu_total': 0, 'lawyer_total': 0,
        'tier': defaultdict(float)
    })) for l in LAWYERS}

    for r in profit:
        lawyer, year, month, tier = r['lawyer'], r['year'], r['month'], r['tier']
        if lawyer not in LAWYERS: continue
        m = monthly[lawyer][year][month]
        A = num(r['commission_A']); B = num(r['refer_B']); C = num(r['consult_C'])
        D = num(r['proc_D'])
        Z = num(r['zhelu_amt']); L = num(r['lawyer_amt'])
        if tier == '諮詢':
            m['consult_a'] += A
            m['tier']['諮詢'] += L
        elif tier in ('委任', '委任2'):
            m['commission_A'] += A
            m['proc_D'] += D
            m['tier']['委任-引案(喆律)'] += B
            m['tier']['委任-咨詢(律師)'] += C
            m['tier']['委任-利潤(喆律)'] += Z
            m['tier']['委任-利潤(律師)'] += L
        elif tier == '自案':
            m['self_A'] += A
            m['tier']['自案(喆律)'] += Z
            m['tier']['自案(律師)'] += L
        else:
            m['tier'][f'{tier}(喆律)'] += Z
            m['tier'][f'{tier}(律師)'] += L

    for r in totals:
        lawyer, year, month = r['lawyer'], r['year'], r['month']
        if lawyer not in LAWYERS: continue
        monthly[lawyer][year][month]['zhelu_total'] = num(r['zhelu_total'])
        monthly[lawyer][year][month]['lawyer_total'] = num(r['lawyer_total'])

    # source
    source_by_lawyer = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'amount': 0}))
    for c in cases:
        if c.get('voided') == '是': continue
        lawyer = c['lawyer']
        source = (c['source'] or '未填') or '未填'
        source_by_lawyer[lawyer][source]['count'] += 1
        source_by_lawyer[lawyer][source]['amount'] += num(c['amount'])

    # repeat-client classification (Tab 5)
    承辦_by_lawyer = defaultdict(list)
    for c in cases:
        if c.get('voided') == '是': continue
        if c.get('section') != '承辦': continue
        d = _parse_date(c.get('date'))
        if d is None: continue
        client = (c.get('client') or '').strip()
        if not client: continue
        承辦_by_lawyer[c['lawyer']].append({'raw': c, 'date': d, 'client': client})

    first_seen = {}
    for l, items in 承辦_by_lawyer.items():
        items.sort(key=lambda x: x['date'])
        for it in items:
            key = (l, it['client'])
            if key not in first_seen:
                first_seen[key] = it['date']

    cases_recent = []
    for c in cases:
        if c.get('voided') == '是': continue
        d = _parse_date(c.get('date'))
        client = (c.get('client') or '').strip()
        classification = 'n/a'
        days_since_first = None
        first_date = None
        if c.get('section') == '承辦' and d is not None and client:
            fs = first_seen.get((c['lawyer'], client))
            if fs is None:
                classification = 'n/a'
            elif fs == d:
                classification = '首委'
                days_since_first = 0
                first_date = d.strftime('%Y-%m-%d')
            else:
                days = (d - fs).days
                days_since_first = days
                first_date = fs.strftime('%Y-%m-%d')
                classification = '1年內續委' if days <= 365 else '1年外續委'
        cases_recent.append({
            'lawyer': c['lawyer'], 'year': c['year'], 'month': c['month'],
            'section': c['section'], 'client': client,
            'amount': num(c['amount']), 'date': c.get('date'),
            'source': c.get('source'), 'brand': c.get('brand'), 'dept': c.get('dept'),
            'classification': classification,
            'days_since_first': days_since_first, 'first_date': first_date,
        })
    cases_recent.sort(key=lambda x: (x['year'] or '', x['month'] or '', -x['amount']), reverse=True)

    # monthly flatten
    monthly_flat = []
    for lawyer in LAWYERS:
        for year, months in monthly[lawyer].items():
            for month, m in months.items():
                monthly_flat.append({
                    'lawyer': lawyer, 'year': year, 'month': month,
                    'commission_A': m['commission_A'],
                    'self_A': m['self_A'],
                    'consult_a': m['consult_a'],
                    'proc_D': m.get('proc_D', 0),
                    'zhelu_total': m['zhelu_total'],
                    'lawyer_total': m['lawyer_total'],
                    'tier': dict(m['tier']),
                })
    monthly_flat.sort(key=lambda x: (x['year'], int(x['month'])))

    source_flat = {l: dict(srcs) for l, srcs in source_by_lawyer.items()}

    # 統一 schema 的 repeat_entries：judicial 從承辦案算，現制 = A × 30%、
    # 新制對「1 年外續委」歸零（變自案），其他維持
    repeat_entries = []
    for c in cases_recent:
        if c.get('section') != '承辦': continue
        if c.get('classification') in (None, 'n/a'): continue
        amt = c['amount']
        cur_zhelu = amt * 0.30
        new_zhelu = 0.0 if c['classification'] == '1年外續委' else cur_zhelu
        repeat_entries.append({
            'lawyer': c['lawyer'], 'year': c['year'], 'month': c['month'],
            'tier': '承辦', 'client': c['client'],
            'case_amount': amt,
            'cur_zhelu': cur_zhelu,
            'new_zhelu': new_zhelu,
            'classification': c['classification'],
            'days_since_first': c['days_since_first'],
            'first_date': c['first_date'],
            'source': c.get('source'),
        })

    return {
        'lawyers': LAWYERS,
        'colors': JUDICIAL_COLORS,
        'contract_matrix': contract_matrix,
        'contract_tiers': JUDICIAL_TIERS,
        'monthly': monthly_flat,
        'sources': source_flat,
        'cases': cases_recent,
        'repeat_entries': repeat_entries,
        'has_repeat_tab': True,
        'repeat_config': {
            'direction': 'zhelu_loses',
            'title': '續委任規則（Block D Q1 討論基礎）',
            'rule_html': (
                '同一律師下同當事人的第 1 次委任後 —<br>'
                '‣ <strong style="color:var(--green)">1 年內再委任</strong>（&le;365 天）'
                '= 喆律案，沿用 30% B 費 + E 分成<br>'
                '‣ <strong style="color:#b58bff">1 年外再委任</strong>（&gt;365 天）'
                '= 律師自案，B = 0%、E 分成比律師端'
            ),
            'kpi_labels': {
                'moved_bucket_name': '1 年外續委總額（會重新歸類）',
                'zhelu_impact_label': '新制下喆律 B 少收',
                'lawyer_impact_label': '新制下律師多拿 B 費',
                'table_col_cur': '現制 B（30%）',
                'table_col_new': '新制 B',
                'table_col_diff': '喆律少收',
            },
        },
    }

# ============================================================
# Cohort 2: 資深轉合署（7 位，新資料管線）
# ============================================================
SENIOR_LAWYERS = ['李昭萱', '林昀', '徐棠娜', '許煜婕', '陳璽仲', '蕭予馨', '吳柏慶']
SENIOR_COLORS = {
    '李昭萱': '#f2b84b',
    '林昀':   '#5dd39e',
    '徐棠娜': '#6aa9ff',
    '許煜婕': '#ff6b6b',
    '陳璽仲': '#b58bff',
    '蕭予馨': '#4ecdc4',
    '吳柏慶': '#ff9f43',
}
SENIOR_TIERS = ['諮詢', '諮詢成案', '喆律轉案', '法律010轉案', '自案', '成案獎金', '其他', '其他-自案']
# 預設規則顯示（合約細節表提供）
SENIOR_DEFAULT_CONTRACT = {
    '諮詢':         '0/100',
    '諮詢成案':     '30/70',
    '喆律轉案':     '40/60',
    '法律010轉案': '30/70',  # 原規則 30/70，後續有改 35/65（出現 0.35 會標 *）
    '自案':         '10/90',
    '成案獎金':     '0/5',
    '其他':         '—',
    '其他-自案':    '—',
}

def build_senior_cohort():
    profit_path = OUT / 'senior_profit_share.csv'
    cases_path = OUT / 'senior_cases.csv'
    totals_path = OUT / 'senior_monthly_totals.csv'
    if not profit_path.exists():
        return None  # senior data not yet generated

    with open(profit_path, encoding='utf-8-sig') as f:
        profit = list(csv.DictReader(f))
    with open(cases_path, encoding='utf-8-sig') as f:
        cases = list(csv.DictReader(f))
    with open(totals_path, encoding='utf-8-sig') as f:
        totals = list(csv.DictReader(f))

    LAWYERS = SENIOR_LAWYERS

    # contract matrix: 預設合約規則 + 記錄律師實際出現過的特殊比例
    contract_matrix = {}
    for lawyer in LAWYERS:
        contract_matrix[lawyer] = dict(SENIOR_DEFAULT_CONTRACT)
    # 用實際資料做 sanity：若某律師某 tier 主要出現比例與預設不合，覆寫
    tier_ratios = defaultdict(lambda: defaultdict(Counter))
    for r in profit:
        tier_ratios[r['lawyer']][r['tier']][round(float(r['ratio']), 3)] += 1
    for lawyer in LAWYERS:
        for tier, ratios in tier_ratios[lawyer].items():
            # 成案獎金例外：合約規則「律師拿 5%」，不是 z/l 兩邊分，固定顯示預設
            if tier == '成案獎金':
                continue
            top_ratio, _ = max(ratios.items(), key=lambda x: x[1])
            if tier in ('自案', '其他-自案', '法律010轉案'):
                # right-side: ratio = 喆律抽成
                z = round(top_ratio * 100)
                l = round((1 - top_ratio) * 100)
            else:
                # left-side: ratio = 律師抽成
                z = round((1 - top_ratio) * 100)
                l = round(top_ratio * 100)
            # only overwrite for tier where default is 「—」(特殊) or 實際比例與預設差異顯著
            default = SENIOR_DEFAULT_CONTRACT.get(tier, '—')
            if default == '—':
                contract_matrix[lawyer][tier] = f'{z}/{l}'
            else:
                # check if top ratio matches default; if 5% 以上差距，標記為特殊
                dz, dl = default.split('/')
                if abs(int(dz) - z) > 5:
                    contract_matrix[lawyer][tier] = f'{z}/{l}*'  # * 表示與標準規則不同

    # monthly aggregate
    monthly = {l: defaultdict(lambda: defaultdict(lambda: {
        'commission_A': 0, 'self_A': 0, 'consult_a': 0,
        'zhelu_total': 0, 'lawyer_total': 0,
        'tier': defaultdict(float)
    })) for l in LAWYERS}

    for r in profit:
        lawyer, year, month, tier = r['lawyer'], r['year'], r['month'], r['tier']
        if lawyer not in LAWYERS: continue
        m = monthly[lawyer][year][month]
        case_amount = num(r['case_amount'])
        Z = num(r['zhelu_amt']); L = num(r['lawyer_amt'])

        if tier == '諮詢':
            m['consult_a'] += case_amount
            m['tier']['諮詢'] += L
        elif tier == '諮詢成案':
            m['commission_A'] += case_amount
            m['tier']['諮詢成案(喆律)'] += Z
            m['tier']['諮詢成案(律師)'] += L
        elif tier == '喆律轉案':
            m['commission_A'] += case_amount
            m['tier']['喆律轉案(喆律)'] += Z
            m['tier']['喆律轉案(律師)'] += L
        elif tier == '法律010轉案':
            # 律師端收款(右表)但由喆律體系帶進，歸 commission 基數
            m['commission_A'] += case_amount
            m['tier']['法律010轉案(喆律)'] += Z
            m['tier']['法律010轉案(律師)'] += L
        elif tier == '自案':
            m['self_A'] += case_amount
            m['tier']['自案(喆律)'] += Z
            m['tier']['自案(律師)'] += L
        elif tier == '成案獎金':
            m['tier']['成案獎金(律師)'] += L
        else:  # 其他 / 其他-自案
            if tier == '其他-自案':
                m['self_A'] += case_amount
            else:
                m['commission_A'] += case_amount
            m['tier'][f'{tier}(喆律)'] += Z
            m['tier'][f'{tier}(律師)'] += L

    for r in totals:
        lawyer, year, month = r['lawyer'], r['year'], r['month']
        if lawyer not in LAWYERS: continue
        monthly[lawyer][year][month]['zhelu_total'] = num(r['zhelu_total'])
        monthly[lawyer][year][month]['lawyer_total'] = num(r['lawyer_total'])

    # source
    source_by_lawyer = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'amount': 0}))
    for c in cases:
        if c.get('voided') == '是': continue
        lawyer = c['lawyer']
        source = (c['source'] or '未填') or '未填'
        source_by_lawyer[lawyer][source]['count'] += 1
        source_by_lawyer[lawyer][source]['amount'] += num(c['amount'])

    # 續委任 classification：同一律師下同當事人
    # 資深律師現制：所有再委任=律師自案（律師 90 / 喆律 10）
    # 新制：1 年內 → 律師 70 / 喆律 30（諮詢成案）；1 年外 → 律師 90 / 喆律 10（維持自案）
    # 金額過低（≤ 2000）視為純諮詢案不納入續委任模擬
    承辦_by_lawyer = defaultdict(list)
    for c in cases:
        if c.get('voided') == '是': continue
        d = _parse_date(c.get('date'))
        if d is None: continue
        client = (c.get('client') or '').strip()
        if not client: continue
        承辦_by_lawyer[c['lawyer']].append({'raw': c, 'date': d, 'client': client})

    first_seen = {}
    for l, items in 承辦_by_lawyer.items():
        items.sort(key=lambda x: x['date'])
        for it in items:
            key = (l, it['client'])
            if key not in first_seen:
                first_seen[key] = it['date']

    cases_recent = []
    for c in cases:
        if c.get('voided') == '是': continue
        d = _parse_date(c.get('date'))
        client = (c.get('client') or '').strip()
        amt = num(c['amount'])
        classification = 'n/a'
        days_since_first = None
        first_date = None
        if d is not None and client and amt > 2000:
            fs = first_seen.get((c['lawyer'], client))
            if fs is None:
                classification = 'n/a'
            elif fs == d:
                classification = '首委'
                days_since_first = 0
                first_date = d.strftime('%Y-%m-%d')
            else:
                days = (d - fs).days
                days_since_first = days
                first_date = fs.strftime('%Y-%m-%d')
                classification = '1年內續委' if days <= 365 else '1年外續委'
        cases_recent.append({
            'lawyer': c['lawyer'], 'year': c['year'], 'month': c['month'],
            'section': c.get('section', '承辦'),
            'client': client,
            'amount': amt, 'date': c.get('date'),
            'source': c.get('source'), 'brand': c.get('brand'), 'dept': c.get('dept'),
            'classification': classification,
            'days_since_first': days_since_first, 'first_date': first_date,
        })
    cases_recent.sort(key=lambda x: (x['year'] or '', x['month'] or '', -x['amount']), reverse=True)

    # monthly flatten
    monthly_flat = []
    for lawyer in LAWYERS:
        for year, months in monthly[lawyer].items():
            for month, m in months.items():
                monthly_flat.append({
                    'lawyer': lawyer, 'year': year, 'month': month,
                    'commission_A': m['commission_A'],
                    'self_A': m['self_A'],
                    'consult_a': m['consult_a'],
                    'proc_D': m.get('proc_D', 0),
                    'zhelu_total': m['zhelu_total'],
                    'lawyer_total': m['lawyer_total'],
                    'tier': dict(m['tier']),
                })
    monthly_flat.sort(key=lambda x: (x['year'], int(x['month'])))

    source_flat = {l: dict(srcs) for l, srcs in source_by_lawyer.items()}

    # repeat_entries：對每筆 profit row 做 classification，現制 = 實際 zhelu_amt、
    # 新制 = 僅對 tier='自案' 且 '1 年內續委' 的案提成 30%，其他維持現況
    # first_seen 從 cases 層級算（date 層級，最精準）
    repeat_entries = []
    for r in profit:
        lawyer = r['lawyer']
        client = (r.get('client') or '').strip()
        if not client: continue
        case_amount = num(r['case_amount'])
        if case_amount <= 2000: continue
        cur_zhelu = num(r['zhelu_amt'])
        year_s = r['year']; month_i = int(r['month'])
        try:
            ad_year = int(year_s) + 1911  # ROC → AD
            approx_date = datetime(ad_year, month_i, 15)
        except Exception:
            continue
        fs = first_seen.get((lawyer, client))
        if fs is None:
            classification = '首委'
            days_since_first = 0
            first_date = approx_date.strftime('%Y-%m-%d')
        elif fs.year == approx_date.year and fs.month == approx_date.month:
            classification = '首委'
            days_since_first = 0
            first_date = fs.strftime('%Y-%m-%d')
        elif fs > approx_date:
            # profit 記錄早於 cases 首日 — 資料完整性問題，以首委對待
            classification = '首委'
            days_since_first = 0
            first_date = approx_date.strftime('%Y-%m-%d')
        else:
            days = (approx_date - fs).days
            days_since_first = days
            first_date = fs.strftime('%Y-%m-%d')
            classification = '1年內續委' if days <= 365 else '1年外續委'

        tier = r['tier']
        if tier == '自案' and classification == '1年內續委':
            new_zhelu = case_amount * 0.30
        else:
            new_zhelu = cur_zhelu
        repeat_entries.append({
            'lawyer': lawyer, 'year': year_s, 'month': month_i,
            'tier': tier, 'client': client,
            'case_amount': case_amount,
            'cur_zhelu': cur_zhelu,
            'new_zhelu': new_zhelu,
            'classification': classification,
            'days_since_first': days_since_first,
            'first_date': first_date,
            'source': None,
        })

    # per-lawyer 特殊 tier（其他 / 其他-自案）案件明細
    # senior profit 是逐筆，可列出該律師實際有的特殊案件
    special_entries = defaultdict(lambda: defaultdict(list))
    for r in profit:
        lawyer = r['lawyer']
        if lawyer not in LAWYERS: continue
        if r['tier'] not in ('其他', '其他-自案'): continue
        client = (r.get('client') or '').strip()
        special_entries[lawyer][r['tier']].append({
            'ym': f"{r['year']}/{int(r['month']):02d}",
            'ratio': round(float(r['ratio']) * 100),
            'client': client,
            'amt': num(r['case_amount']),
        })
    special_tier_tips = {}
    for lawyer, tier_map in special_entries.items():
        special_tier_tips[lawyer] = {}
        for tier, entries in tier_map.items():
            entries.sort(key=lambda e: (e['ym'], -abs(e['amt'])))
            lines = []
            for e in entries[:8]:
                c = e['client'] if len(e['client']) <= 18 else e['client'][:18] + '…'
                lines.append(f"{e['ym']} {c} ${int(e['amt']):,} ({e['ratio']}%)")
            suffix = '' if len(entries) <= 8 else f'\n…（另 {len(entries)-8} 筆）'
            special_tier_tips[lawyer][tier] = (lawyer + ' 的「' + tier + '」明細：\n' +
                                                '\n'.join(lines) + suffix)

    return {
        'lawyers': LAWYERS,
        'colors': SENIOR_COLORS,
        'contract_matrix': contract_matrix,
        'contract_tiers': SENIOR_TIERS,
        'monthly': monthly_flat,
        'sources': source_flat,
        'cases': cases_recent,
        'repeat_entries': repeat_entries,
        'special_tier_tips': special_tier_tips,
        'has_repeat_tab': True,
        'repeat_config': {
            'direction': 'zhelu_gains',
            'title': '續委任規則（資深律師現制 vs 新制）',
            'rule_html': (
                '每筆案依其實際 tier（諮詢成案/喆律轉案/自案/法律010轉案）分潤，此處分析「續委任條款」的影響 —<br>'
                '‣ <strong style="color:#8b93a3">現制</strong>：各 tier 按合約原比例分（自案喆律 10%、諮詢成案 30%、'
                '喆律轉案 40%、法律010轉案 30%…）<br>'
                '‣ <strong style="color:var(--gold)">新制</strong>：僅對 '
                '<span style="color:var(--green)">「原本歸為律師自案」且 1 年內續委</span> 的案件，'
                '由 10% 提升為 30%（視同諮詢成案）；其他案件維持原比例'
            ),
            'kpi_labels': {
                'moved_bucket_name': '受影響案件總額（自案且 1 年內續委）',
                'zhelu_impact_label': '新制下喆律多收',
                'lawyer_impact_label': '新制下律師少拿',
                'table_col_cur': '現制喆律（各 tier 實收）',
                'table_col_new': '新制喆律',
                'table_col_diff': '喆律多收',
            },
        },
    }

# ============================================================
# Build both cohorts
# ============================================================
cohorts = {
    'judicial': build_judicial_cohort(),
    'senior':   build_senior_cohort(),
}
data = {
    'cohorts': {k: v for k, v in cohorts.items() if v is not None},
    'default_cohort': 'judicial',
    'cohort_labels': {
        'judicial': '司法官合署（4 位）',
        'senior':   '資深轉合署（7 位）',
    },
}

# ============================================================
# HTML TEMPLATE
# ============================================================
HTML = r'''<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>喆律合署律師分析（共識營原型）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>
:root {
  --bg:#0e1116; --bg2:#161a22; --bg3:#1f2631;
  --fg:#e4e7ee; --fg-dim:#8b93a3;
  --line:#2a3140;
  --gold:#f2b84b; --blue:#6aa9ff; --red:#ff6b6b; --green:#5dd39e;
}
* {box-sizing:border-box}
body {margin:0; font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif; background:var(--bg); color:var(--fg); font-size:14px}
.wrap {max-width:1400px; margin:0 auto; padding:24px}
header {display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid var(--line); padding-bottom:16px; margin-bottom:20px}
header h1 {margin:0; font-size:22px; font-weight:600}
header .subtitle {color:var(--fg-dim); font-size:13px; margin-top:4px}
header .year-filter {display:flex; gap:4px}
.year-btn {background:var(--bg2); color:var(--fg-dim); border:1px solid var(--line); padding:6px 14px; border-radius:4px; cursor:pointer; font-size:13px}
.year-btn.active {background:var(--gold); color:#111; border-color:var(--gold); font-weight:600}
.year-btn:hover:not(.active) {color:var(--fg); border-color:var(--fg-dim)}

.cohort-bar {display:flex; gap:8px; margin-bottom:16px; align-items:center}
.cohort-bar .cohort-label {color:var(--fg-dim); font-size:13px; margin-right:4px}
.cohort-pill {background:var(--bg2); color:var(--fg); border:1px solid var(--line); padding:8px 18px; border-radius:999px; cursor:pointer; font-size:13px; font-weight:500}
.cohort-pill.active {background:var(--gold); color:#111; border-color:var(--gold)}
.cohort-pill:hover:not(.active) {border-color:var(--fg-dim)}

.tabs {display:flex; gap:2px; margin-bottom:20px; border-bottom:1px solid var(--line)}
.tab-btn {background:transparent; color:var(--fg-dim); border:none; padding:10px 18px; cursor:pointer; font-size:14px; border-bottom:2px solid transparent}
.tab-btn.active {color:var(--gold); border-bottom-color:var(--gold)}
.tab-btn:hover:not(.active) {color:var(--fg)}
.tab-btn.hidden {display:none}

.page {display:none}
.page.active {display:block}

.grid {display:grid; gap:16px}
.grid-2 {grid-template-columns:repeat(2, 1fr)}
.grid-3 {grid-template-columns:repeat(3, 1fr)}
.grid-4 {grid-template-columns:repeat(4, 1fr)}

.card {background:var(--bg2); border:1px solid var(--line); border-radius:8px; padding:16px}
.card h3 {margin:0 0 12px; font-size:14px; font-weight:600; color:var(--fg-dim); letter-spacing:0.5px}
.card .note {font-size:12px; color:var(--fg-dim); margin-top:8px}

.kpi {background:var(--bg2); border:1px solid var(--line); border-radius:8px; padding:14px}
.kpi .label {font-size:12px; color:var(--fg-dim); margin-bottom:6px}
.kpi .value {font-size:22px; font-weight:600; color:var(--fg)}
.kpi .sub {font-size:11px; color:var(--fg-dim); margin-top:4px}

table {width:100%; border-collapse:collapse; font-size:13px}
th, td {padding:8px 10px; text-align:left; border-bottom:1px solid var(--line)}
th {color:var(--fg-dim); font-weight:500; font-size:12px}
td.num {text-align:right; font-variant-numeric:tabular-nums}
th.num {text-align:right}

.chart-box {position:relative; height:320px}
.chart-box.tall {height:420px}
.chart-box.short {height:240px}

.pct-matrix {font-size:13px}
.pct-matrix td, .pct-matrix th {padding:8px; border:1px solid var(--line)}
.pct-matrix th {background:var(--bg3); font-weight:500}
.pct-matrix td:first-child {font-weight:500}
.pct-cell {text-align:center; font-variant-numeric:tabular-nums}
.pct-cell.premium {color:var(--green); font-weight:500}
.pct-cell.standard {color:var(--gold)}
.pct-cell.firm-heavy {color:var(--red); font-weight:500}
.pct-cell.derived {color:#b58bff; font-size:11px; font-weight:500; cursor:help}
.pct-cell.special {color:#b58bff; font-weight:500}
.diff-cell {cursor:pointer; text-decoration:underline dotted; text-underline-offset:3px}
.diff-cell:hover {filter:brightness(1.3)}
.detail-row > td {background:var(--bg3); padding:8px 14px}
.detail-row table {background:var(--bg2); border-radius:4px; overflow:hidden}
.detail-row thead th {background:var(--bg3); font-size:11px}

.lawyer-dot {display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:middle}

select {background:var(--bg3); color:var(--fg); border:1px solid var(--line); padding:6px 10px; border-radius:4px; font-size:13px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>喆律合署律師財務分析</h1>
      <div class="subtitle" id="subtitle">共識營原型 · 4 位司法官合署 + 7 位資深轉合署律師</div>
    </div>
    <div class="year-filter" id="year-filter"></div>
  </header>

  <div class="cohort-bar">
    <span class="cohort-label">律師族群</span>
    <div id="cohort-pills"></div>
  </div>

  <div class="tabs" id="tabs">
    <button class="tab-btn active" data-tab="overview">① 總覽（喆律視角）</button>
    <button class="tab-btn" data-tab="compare">② 律師對比</button>
    <button class="tab-btn" data-tab="source">③ 來源結構</button>
    <button class="tab-btn" data-tab="drill">④ 個別律師鑽取</button>
    <button class="tab-btn" data-tab="repeat">⑤ 續委任分析</button>
  </div>

  <!-- ========== TAB 1: OVERVIEW ========== -->
  <section class="page active" id="page-overview">
    <div class="card" style="margin-bottom:16px">
      <h3 id="matrix-title">合約分潤矩陣（共識營核心討論點）</h3>
      <table class="pct-matrix" id="pct-matrix"></table>
      <div class="note" id="matrix-note"></div>
    </div>

    <div class="grid grid-4" id="kpi-cards"></div>

    <div class="grid grid-2" style="margin-top:16px">
      <div class="card">
        <h3>月度堆疊 · 喆律總收入 × 律師</h3>
        <div class="chart-box tall"><canvas id="chart-monthly-zhelu"></canvas></div>
      </div>
      <div class="card">
        <h3>月度堆疊 · 律師總收入 × 律師</h3>
        <div class="chart-box tall"><canvas id="chart-monthly-lawyer"></canvas></div>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top:16px">
      <div class="card">
        <h3>喆律收入的 tier 組成（當期）</h3>
        <div class="chart-box"><canvas id="chart-zhelu-composition"></canvas></div>
        <div class="note">看喆律的收入結構是「平台抽成」還是「引案費」主導。</div>
      </div>
      <div class="card">
        <h3>喆律毛利率（喆律收入 ÷ 案件總額 A）</h3>
        <div class="chart-box"><canvas id="chart-margin"></canvas></div>
        <div class="note">喆律從律師帶進的案件中抽走的比例。</div>
      </div>
    </div>
  </section>

  <!-- ========== TAB 2: COMPARE ========== -->
  <section class="page" id="page-compare">
    <div class="grid grid-2">
      <div class="card">
        <h3>律師核心指標雷達圖（當期）</h3>
        <div class="chart-box tall"><canvas id="chart-radar"></canvas></div>
        <div class="note">五軸：委任費、諮詢費、自案金額、喆律貢獻、客戶來源多元性。各軸在本族群律師間相對歸一化。</div>
      </div>
      <div class="card">
        <h3>月度喆律貢獻折線（依律師）</h3>
        <div class="chart-box tall"><canvas id="chart-line-zhelu"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>律師年度 KPI 對比表</h3>
      <table id="kpi-table"></table>
    </div>
  </section>

  <!-- ========== TAB 3: SOURCE ========== -->
  <section class="page" id="page-source">
    <div class="grid grid-2">
      <div class="card">
        <h3>客戶來源分佈（按案件金額）</h3>
        <div class="chart-box tall"><canvas id="chart-source-pie"></canvas></div>
      </div>
      <div class="card">
        <h3>各律師的來源結構（金額 %）</h3>
        <div class="chart-box tall"><canvas id="chart-source-bar"></canvas></div>
        <div class="note">觀察重點：合署律師對「喆律轉案 / 法律零一零」的依賴程度。</div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>各來源的案件數與總金額</h3>
      <table id="source-table"></table>
    </div>
  </section>

  <!-- ========== TAB 4: DRILL ========== -->
  <section class="page" id="page-drill">
    <div style="margin-bottom:16px; display:flex; align-items:center; gap:12px; flex-wrap:wrap">
      <label style="color:var(--fg-dim)">選擇律師</label>
      <select id="drill-lawyer"></select>
      <button id="tier-def-toggle" type="button" class="btn-sm" style="margin-left:auto; cursor:pointer">tier 類型說明 ▾</button>
    </div>
    <div id="tier-def-panel" class="card" style="display:none; margin-bottom:16px">
      <h3 style="margin-bottom:10px">tier 類型速查（用來對照 KPI 的「主案／附屬」分類）</h3>
      <div style="overflow-x:auto">
        <table style="min-width:640px">
          <thead><tr><th style="width:18%">tier</th><th style="width:14%">類別</th><th>意義</th></tr></thead>
          <tbody>
            <tr><td colspan="3" style="background:var(--bg-row); color:var(--gold-light); font-weight:600; padding:6px 10px">— 司法官合署 —</td></tr>
            <tr><td>委任-引案(喆律)</td><td><span class="badge badge-orange">主案 B</span></td><td>委任費 A × 30%，客戶由喆律帶來的引案費，歸喆律</td></tr>
            <tr><td>委任-咨詢(律師)</td><td><span class="badge badge-blue">主案 C</span></td><td>委任費 A × 10%，律師諮詢貢獻歸律師</td></tr>
            <tr><td>委任-利潤 E（喆律/律師）</td><td><span class="badge badge-green">主案 E</span></td><td>A − B − C − D 剩餘利潤，按合約比例分（50/50 或 15/85）</td></tr>
            <tr><td>處理費 D</td><td><span class="badge badge-orange">主案成本</span></td><td>共擔成本（人事薪資、員工交通、閱卷、刷卡手續費等），從 A 扣除</td></tr>
            <tr><td>自案(喆律/律師)</td><td><span class="badge badge-green">主案</span></td><td>律師自招案件，劉/方 10/90、孫/許 5/95 分</td></tr>
            <tr><td colspan="3" style="background:var(--bg-row); color:var(--gold-light); font-weight:600; padding:6px 10px">— 資深轉合署 —</td></tr>
            <tr><td>諮詢成案(喆律/律師)</td><td><span class="badge badge-green">主案</span></td><td>律師諮詢後自己承辦的案件，30/70 分</td></tr>
            <tr><td>喆律轉案(喆律/律師)</td><td><span class="badge badge-green">主案</span></td><td>喆律轉入由資深律師承辦，40/60 分</td></tr>
            <tr><td>法律010轉案(喆律/律師)</td><td><span class="badge badge-green">主案</span></td><td>法律010 品牌轉入的案件，30/70 分（部分律師後調為 35/65）</td></tr>
            <tr><td>自案(喆律/律師)</td><td><span class="badge badge-green">主案</span></td><td>資深律師自招案件，10/90 分</td></tr>
            <tr><td colspan="3" style="background:var(--bg-row); color:var(--gold-light); font-weight:600; padding:6px 10px">— 附屬收入（雙 cohort 共通）—</td></tr>
            <tr><td>諮詢</td><td><span class="badge badge-blue">附屬</span></td><td>律師為客戶諮詢的諮詢費（100% 歸律師，通常 $2,000/場）</td></tr>
            <tr><td>介紹(律師)</td><td><span class="badge badge-blue">附屬</span></td><td>律師介紹給他人承辦，取 10%（自然人）/ 20%（公司）佣金</td></tr>
            <tr><td>追溯(律師)</td><td><span class="badge badge-blue">附屬</span></td><td>過去介紹費事後補/扣的修正</td></tr>
            <tr><td>轉案(喆律/律師)</td><td><span class="badge badge-blue">附屬</span></td><td>律師之間或與喆律之間的案件轉介分潤（非主案轉案）</td></tr>
            <tr><td>受僱(喆律/律師)</td><td><span class="badge badge-blue">附屬</span></td><td>律師替他人承辦的案件分潤</td></tr>
            <tr><td>續委(喆律/律師)</td><td><span class="badge badge-blue">附屬</span></td><td>舊客戶後續委任衍生的分潤</td></tr>
            <tr><td>合作(喆律/律師)</td><td><span class="badge badge-blue">附屬</span></td><td>多律師合作案的分潤</td></tr>
            <tr><td>成案獎金(律師)</td><td><span class="badge badge-blue">附屬</span></td><td>（資深諮詢律師）諮詢後由他人承辦，抽成 5% 獎金</td></tr>
            <tr><td>其他（左表）</td><td><span class="badge badge-blue">附屬</span></td><td>資深律師端的左表（喆律收款）比例非標準 0.7 / 0.6 / 1.0 的案件，僅 11 筆（主要陳璽仲 115/3 的 0.4 案、蕭予馨 2 筆 0.9 等）</td></tr>
            <tr><td>其他-自案（右表）</td><td><span class="badge badge-blue">附屬</span></td><td>資深律師端右表（律師收款付喆律）但比例既非 0.1（標準自案）也非 0.3 / 0.35（法律010 轉案）的案件，全庫僅 5 筆：4 筆 40%（含林昀法扶舊案、退款、吳柏慶/蕭予馨各 1 筆）+ 1 筆 60%（陳璽仲王斯弘特殊協議）</td></tr>
          </tbody>
        </table>
      </div>
      <div class="note" style="margin-top:10px">
        「主案」收入全部來自「主案件金額」（委任 + 自案）的拆分；「附屬」收入另外發生，不在主案件金額範圍內。
      </div>
    </div>
    <div class="grid grid-4" id="drill-kpi" style="margin-bottom:16px"></div>
    <div class="grid grid-2">
      <div class="card">
        <h3>月度 tier 組成（喆律側）</h3>
        <div class="chart-box tall"><canvas id="chart-drill-tier-z"></canvas></div>
      </div>
      <div class="card">
        <h3>月度 tier 組成（律師側）</h3>
        <div class="chart-box tall"><canvas id="chart-drill-tier-l"></canvas></div>
      </div>
    </div>
  </section>

  <!-- ========== TAB 5: REPEAT CLIENT ========== -->
  <section class="page" id="page-repeat">
    <div class="card" style="margin-bottom:16px">
      <h3 id="repeat-rule-title">續委任規則</h3>
      <div id="repeat-rule-body" style="line-height:1.7; color:var(--fg)"></div>
    </div>

    <div class="grid grid-4" id="repeat-kpi"></div>

    <div class="grid grid-2" style="margin-top:16px">
      <div class="card">
        <h3>各律師承辦案件 · 首委 / 1 年內續委 / 1 年外續委</h3>
        <div class="chart-box tall"><canvas id="chart-repeat-stack"></canvas></div>
      </div>
      <div class="card">
        <h3>續委任間隔天數分布</h3>
        <div class="chart-box tall"><canvas id="chart-repeat-hist"></canvas></div>
        <div class="note">橫軸：距首委天數；紅色虛線 = 365 天規則線</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3 id="repeat-table-title">新制 vs 現制 · 喆律抽成影響（當期）</h3>
      <table id="repeat-comparison-table"></table>
    </div>

    <div class="card" style="margin-top:16px">
      <h3 id="repeat-moved-title">被新制重新歸類的案件（當期，依金額降序，上限 50 筆）</h3>
      <table id="repeat-moved-cases"></table>
    </div>
  </section>

</div>

<script id="embedded-data" type="application/json">__DATA__</script>
<script>
const RAW = JSON.parse(document.getElementById('embedded-data').textContent);
const fmt = n => (n||0).toLocaleString('zh-TW', {maximumFractionDigits:0});
const fmtPct = n => ((n||0)*100).toFixed(1) + '%';

// ---- state ----
let selectedCohort = RAW.default_cohort;
let DATA = RAW.cohorts[selectedCohort];
let LAWYERS = DATA.lawyers;
let COLORS = DATA.colors;
let selectedYear = 'all';
let drillLawyer = LAWYERS[0];

// 一筆案件若 source 含逗號，拆開；每個來源各算 1 件、金額平均拆分。
function splitSources(src) {
  if (!src) return ['未填'];
  const parts = String(src).split(/[,，、]/).map(s => s.trim()).filter(Boolean);
  return parts.length ? parts : ['未填'];
}
Chart.defaults.color = '#8b93a3';
Chart.defaults.borderColor = '#2a3140';
Chart.defaults.font.family = 'inherit';

// ---- cohort pills ----
function renderCohortPills() {
  const el = document.getElementById('cohort-pills');
  const cohorts = Object.keys(RAW.cohorts);
  el.innerHTML = cohorts.map(c =>
    `<button class="cohort-pill ${c===selectedCohort?'active':''}" data-c="${c}" style="margin-right:6px">${RAW.cohort_labels[c]}</button>`
  ).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => switchCohort(b.dataset.c));
}

function switchCohort(c) {
  if (c === selectedCohort) return;
  selectedCohort = c;
  DATA = RAW.cohorts[c];
  LAWYERS = DATA.lawyers;
  COLORS = DATA.colors;
  drillLawyer = LAWYERS[0];
  updateTabVisibility();
  renderDrillSelector();
  // reset year filter if current year not in new cohort
  const years = [...new Set(DATA.monthly.map(m=>m.year))];
  if (selectedYear !== 'all' && !years.includes(selectedYear)) {
    selectedYear = years.sort().slice(-1)[0] || 'all';
  }
  // update cohort pill UI
  document.querySelectorAll('.cohort-pill').forEach(b => {
    b.classList.toggle('active', b.dataset.c === c);
  });
  renderAll();
}

function updateTabVisibility() {
  // Tab 5 只給 judicial cohort；若切換到不支援 repeat 的 cohort 且當前是 repeat，切到 overview
  document.querySelectorAll('.tab-btn').forEach(b => {
    const allowed = b.dataset.cohorts;
    if (!allowed) { b.classList.remove('hidden'); return; }
    const ok = allowed.split(',').includes(selectedCohort);
    b.classList.toggle('hidden', !ok);
    if (!ok && b.classList.contains('active')) {
      // switch to first visible tab
      b.classList.remove('active');
      document.getElementById('page-'+b.dataset.tab).classList.remove('active');
      const first = document.querySelector('.tab-btn:not(.hidden)');
      first.classList.add('active');
      document.getElementById('page-'+first.dataset.tab).classList.add('active');
    }
  });
}

function filteredMonthly(year) {
  return year === 'all' ? DATA.monthly : DATA.monthly.filter(m => m.year === year);
}

// ---- year filter ----
function renderYearFilter() {
  const years = ['all', ...new Set(DATA.monthly.map(m=>m.year).sort())];
  const el = document.getElementById('year-filter');
  el.innerHTML = years.map(y => {
    const label = y === 'all' ? '全部' : `${y} 年`;
    return `<button class="year-btn ${y===selectedYear?'active':''}" data-y="${y}">${label}</button>`;
  }).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => {
    selectedYear = b.dataset.y;
    renderAll();
  });
}

// ---- Tab 1: Overview ----
const JUDICIAL_DERIVED_TIERS = {
  '介紹': {label:'取他案 10-20%', note:'介紹給他人承辦 → 自然人取 10%、法人取 20%'},
  '追溯': {label:'介紹費修正', note:'過去介紹費事後補/扣'},
};

function renderContractMatrix() {
  const tiers = DATA.contract_tiers;
  const tbl = document.getElementById('pct-matrix');
  const isJudicial = selectedCohort === 'judicial';
  let html = '<thead><tr><th>律師</th>' + tiers.map(t=>`<th>${t}</th>`).join('') + '</tr></thead><tbody>';
  for (const l of LAWYERS) {
    html += `<tr><td><span class="lawyer-dot" style="background:${COLORS[l]}"></span>${l}</td>`;
    for (const t of tiers) {
      const v = (DATA.contract_matrix[l]||{})[t];
      if (!v || v === '—') { html += '<td class="pct-cell" style="color:#445">—</td>'; continue; }
      if (isJudicial && JUDICIAL_DERIVED_TIERS[t]) {
        const d = JUDICIAL_DERIVED_TIERS[t];
        html += `<td class="pct-cell derived" title="${d.note}">${d.label}</td>`;
        continue;
      }
      // special marker * = 實際比例與預設規則不同
      const isSpecial = typeof v === 'string' && v.endsWith('*');
      const clean = isSpecial ? v.slice(0, -1) : v;
      const parts = clean.split('/').map(Number);
      const z = parts[0];
      let cls = 'standard';
      if (isSpecial) cls = 'special';
      else if (z === 0) cls = 'premium';
      else if (z >= 40) cls = 'firm-heavy';
      const title = isSpecial ? '與預設合約規則不同' : '';
      html += `<td class="pct-cell ${cls}" title="${title}">${v}</td>`;
    }
    html += '</tr>';
  }
  tbl.innerHTML = html + '</tbody>';

  // note
  document.getElementById('matrix-note').innerHTML = isJudicial
    ? '* 比例為「喆律 / 律師」；孫、許的自案在 113 年中從 15/85 調為 5/95（取主要出現比例）。<br>'
      + '* 委任案的引案（A×30%）與咨詢（A×10%）在計算利潤 E 之前先扣除 — 引案歸喆律、咨詢歸律師。E 剩餘部分再按比例分。<br>'
      + '* <span style="color:#b58bff">介紹 / 追溯</span> 是「依附他人案件」的衍生項。'
    : '* 比例為「喆律 / 律師」。預設規則：諮詢成案 30/70、喆律轉案 40/60、自案 10/90、純諮詢 0/100、成案獎金律師額外得 5%。<br>'
      + '* <span style="color:#b58bff">標 * 的比例</span>：該律師實際資料出現頻率最高的比例與預設規則不同（通常為特殊協議或混合案型）。<br>'
      + '* 「其他」為解析時未對上標準比例的案件（如 0.35 / 0.4 / 0.3 等），保留供後續規則釐清。';
}

function aggregateYear(monthly) {
  const byLawyer = {};
  for (const l of LAWYERS) byLawyer[l] = {
    commission_A:0, self_A:0, consult_a:0, zhelu_total:0, lawyer_total:0, months:0
  };
  for (const m of monthly) {
    const b = byLawyer[m.lawyer]; if (!b) continue;
    b.commission_A += m.commission_A;
    b.self_A += m.self_A;
    b.consult_a += m.consult_a;
    b.zhelu_total += m.zhelu_total;
    b.lawyer_total += m.lawyer_total;
    b.months += 1;
  }
  return byLawyer;
}

function aggregateYearFull(monthly) {
  // include proc_D
  const byLawyer = aggregateYear(monthly);
  for (const m of monthly) {
    if (byLawyer[m.lawyer]) byLawyer[m.lawyer].proc_D = (byLawyer[m.lawyer].proc_D || 0) + (m.proc_D || 0);
  }
  return byLawyer;
}

function renderKPI() {
  const data = aggregateYearFull(filteredMonthly(selectedYear));
  const totalA = Object.values(data).reduce((s,d)=>s+d.commission_A+d.self_A, 0);
  const totalZ = Object.values(data).reduce((s,d)=>s+d.zhelu_total, 0);
  const totalL = Object.values(data).reduce((s,d)=>s+d.lawyer_total, 0);
  const totalD = Object.values(data).reduce((s,d)=>s+(d.proc_D||0), 0);
  const lawyerCount = LAWYERS.length;
  const isJudicial = selectedCohort === 'judicial';
  const dSub = isJudicial && totalD > 0
    ? `<br><span style="color:var(--orange)">內扣處理費 D $${fmt(totalD)}（人事等共擔成本）</span>`
    : '';

  const el = document.getElementById('kpi-cards');
  el.innerHTML = `
    <div class="kpi"><div class="label">總案件金額（${lawyerCount} 位律師合計）</div>
      <div class="value">$${fmt(totalA)}</div>
      <div class="sub">委任案 + 自案的總額${dSub}</div></div>
    <div class="kpi"><div class="label">喆律總收入</div>
      <div class="value" style="color:var(--gold)">$${fmt(totalZ)}</div>
      <div class="sub">引案費 + 利潤分成 + 其他 tier</div></div>
    <div class="kpi"><div class="label">律師總收入</div>
      <div class="value" style="color:var(--blue)">$${fmt(totalL)}</div>
      <div class="sub">諮詢 + 咨詢 + 分成 + 其他</div></div>
    <div class="kpi"><div class="label">喆律 / 律師 收入比</div>
      <div class="value">${totalL>0 ? (totalZ/totalL).toFixed(2) : '—'}</div>
      <div class="sub">= 1.0 代表平分；&lt; 1 律師拿大頭；&gt; 1 喆律吃較多</div></div>`;
}

const charts = {};
function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }

function renderMonthlyStacked(canvasId, field) {
  destroyChart(canvasId);
  const monthly = filteredMonthly(selectedYear);
  const yms = [...new Set(monthly.map(m => `${m.year}/${String(m.month).padStart(2,'0')}`))].sort();
  const datasets = LAWYERS.map(l => ({
    label: l,
    backgroundColor: COLORS[l],
    data: yms.map(ym => {
      const [y, mo] = ym.split('/');
      const rec = monthly.find(x => x.lawyer===l && x.year===y && String(x.month).padStart(2,'0')===mo);
      return rec ? rec[field] : 0;
    })
  }));
  charts[canvasId] = new Chart(document.getElementById(canvasId), {
    type: 'bar',
    data: { labels: yms, datasets },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales: { x:{stacked:true}, y:{stacked:true, ticks:{callback:v=>fmt(v)}} },
      plugins: { tooltip: {callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });
}

function renderZhelCompDoughnut() {
  destroyChart('chart-zhelu-composition');
  const monthly = filteredMonthly(selectedYear);
  const comp = {};
  for (const m of monthly) {
    for (const [k,v] of Object.entries(m.tier)) {
      if (k.includes('(喆律)')) comp[k] = (comp[k]||0) + v;
    }
  }
  const entries = Object.entries(comp).filter(([,v])=>v!==0).sort((a,b)=>b[1]-a[1]);
  const palette = ['#f2b84b','#6aa9ff','#ff6b6b','#5dd39e','#b58bff','#ff9f43','#4ecdc4','#ffa8a8','#6dd5ed','#ffd166','#c9a06b','#a0a5b2'];
  charts['chart-zhelu-composition'] = new Chart(document.getElementById('chart-zhelu-composition'), {
    type: 'doughnut',
    data: {
      labels: entries.map(e=>e[0].replace('(喆律)','')),
      datasets: [{ data: entries.map(e=>e[1]), backgroundColor: palette.slice(0, entries.length) }]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ tooltip:{callbacks:{label:c=>`${c.label}: $${fmt(c.parsed)}`}} }
    }
  });
}

function renderMarginBar() {
  destroyChart('chart-margin');
  const data = aggregateYear(filteredMonthly(selectedYear));
  charts['chart-margin'] = new Chart(document.getElementById('chart-margin'), {
    type: 'bar',
    data: {
      labels: LAWYERS,
      datasets: [{
        label: '喆律毛利率',
        data: LAWYERS.map(l => {
          const d = data[l];
          const base = d.commission_A + d.self_A;
          return base > 0 ? d.zhelu_total / base : 0;
        }),
        backgroundColor: LAWYERS.map(l=>COLORS[l])
      }]
    },
    options: {
      responsive:true, maintainAspectRatio:false, indexAxis:'y',
      scales: {x: {ticks: {callback: v=>(v*100).toFixed(0)+'%'}}},
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>fmtPct(c.parsed.x)}} }
    }
  });
}

// ---- Tab 2: Compare ----
function renderRadar() {
  destroyChart('chart-radar');
  const data = aggregateYear(filteredMonthly(selectedYear));
  const axes = ['委任案','諮詢費','自案','喆律貢獻','來源多元性'];
  const cs = filteredCases(selectedYear);
  const uniqSrcByLawyer = {};
  for (const l of LAWYERS) uniqSrcByLawyer[l] = new Set();
  for (const c of cs) {
    const set = uniqSrcByLawyer[c.lawyer];
    if (!set) continue;
    for (const s of splitSources(c.source)) set.add(s);
  }
  const rawByAxis = {
    委任案: LAWYERS.map(l=>data[l].commission_A),
    諮詢費: LAWYERS.map(l=>data[l].consult_a),
    自案: LAWYERS.map(l=>data[l].self_A),
    喆律貢獻: LAWYERS.map(l=>data[l].zhelu_total),
    來源多元性: LAWYERS.map(l=>uniqSrcByLawyer[l].size),
  };
  const maxes = Object.fromEntries(axes.map(a=>[a, Math.max(1,...rawByAxis[a])]));
  const datasets = LAWYERS.map(l => ({
    label: l,
    backgroundColor: COLORS[l]+'40',
    borderColor: COLORS[l],
    borderWidth: 2,
    pointBackgroundColor: COLORS[l],
    pointRadius: 3,
    fill: true,
    data: axes.map((a,i)=>rawByAxis[a][LAWYERS.indexOf(l)] / maxes[a] * 100)
  }));
  charts['chart-radar'] = new Chart(document.getElementById('chart-radar'), {
    type: 'radar',
    data: { labels: axes, datasets },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales: { r: { min:0, max:100, grid:{color:'#2a3140'}, angleLines:{color:'#2a3140'}, pointLabels:{color:'#e4e7ee'} } }
    }
  });
}

function renderLineZhelu() {
  destroyChart('chart-line-zhelu');
  const monthly = filteredMonthly(selectedYear);
  const yms = [...new Set(monthly.map(m => `${m.year}/${String(m.month).padStart(2,'0')}`))].sort();
  const datasets = LAWYERS.map(l => ({
    label: l,
    borderColor: COLORS[l],
    backgroundColor: COLORS[l]+'22',
    pointBackgroundColor: COLORS[l],
    pointRadius: 4,
    pointHoverRadius: 6,
    borderWidth: 2,
    tension: 0.25,
    spanGaps: true,
    data: yms.map(ym => {
      const [y, mo] = ym.split('/');
      const rec = monthly.find(x => x.lawyer===l && x.year===y && String(x.month).padStart(2,'0')===mo);
      return rec ? rec.zhelu_total : null;
    })
  }));
  charts['chart-line-zhelu'] = new Chart(document.getElementById('chart-line-zhelu'), {
    type: 'line',
    data: { labels: yms, datasets },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales: { y: { ticks: { callback: v=>fmt(v) } } },
      plugins: { tooltip: {callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });
}

function renderKPITable() {
  const data = aggregateYearFull(filteredMonthly(selectedYear));
  const tbl = document.getElementById('kpi-table');
  const isJudicial = selectedCohort === 'judicial';
  const dHeader = isJudicial ? '<th class="num" title="處理費 D（人事等共擔成本，僅司法官合署適用）">處理費 D</th>' : '';
  let html = `<thead><tr>
    <th>律師</th><th>月數</th>
    <th class="num">委任案總額</th><th class="num">自案總額</th><th class="num">諮詢費總額</th>
    ${dHeader}
    <th class="num">喆律總收</th><th class="num">律師總收</th>
    <th class="num">喆律佔比</th><th class="num">喆律/律師比</th>
  </tr></thead><tbody>`;
  for (const l of LAWYERS) {
    const d = data[l];
    const share = (d.zhelu_total + d.lawyer_total) > 0 ? d.zhelu_total / (d.zhelu_total + d.lawyer_total) : 0;
    const ratio = d.lawyer_total > 0 ? d.zhelu_total / d.lawyer_total : 0;
    const dCell = isJudicial ? `<td class="num" style="color:var(--orange)">$${fmt(d.proc_D||0)}</td>` : '';
    html += `<tr>
      <td><span class="lawyer-dot" style="background:${COLORS[l]}"></span>${l}</td>
      <td>${d.months}</td>
      <td class="num">$${fmt(d.commission_A)}</td>
      <td class="num">$${fmt(d.self_A)}</td>
      <td class="num">$${fmt(d.consult_a)}</td>
      ${dCell}
      <td class="num" style="color:var(--gold)">$${fmt(d.zhelu_total)}</td>
      <td class="num" style="color:var(--blue)">$${fmt(d.lawyer_total)}</td>
      <td class="num">${fmtPct(share)}</td>
      <td class="num">${ratio.toFixed(2)}</td>
    </tr>`;
  }
  tbl.innerHTML = html + '</tbody>';
}

// ---- Tab 3: Source ----
function filteredCases(year) {
  return year === 'all' ? DATA.cases : DATA.cases.filter(c => c.year === year);
}

function renderSourcePie() {
  destroyChart('chart-source-pie');
  const cases = filteredCases(selectedYear);
  const agg = {};
  for (const c of cases) {
    const parts = splitSources(c.source);
    const share = c.amount / parts.length;
    for (const s of parts) agg[s] = (agg[s]||0) + share;
  }
  const entries = Object.entries(agg).sort((a,b)=>b[1]-a[1]);
  const palette = ['#f2b84b','#6aa9ff','#ff6b6b','#5dd39e','#b58bff','#ff9f43','#4ecdc4','#ffa8a8','#6dd5ed','#ffd166'];
  charts['chart-source-pie'] = new Chart(document.getElementById('chart-source-pie'), {
    type: 'pie',
    data: { labels: entries.map(e=>e[0]), datasets:[{ data:entries.map(e=>e[1]), backgroundColor: palette }] },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ tooltip:{callbacks:{label:c=>`${c.label}: $${fmt(c.parsed)}`}} }
    }
  });
}

function renderSourceBar() {
  destroyChart('chart-source-bar');
  const cases = filteredCases(selectedYear);
  const bySrcLaw = {};
  for (const c of cases) {
    const parts = splitSources(c.source);
    const share = c.amount / parts.length;
    for (const s of parts) {
      bySrcLaw[s] = bySrcLaw[s] || {};
      bySrcLaw[s][c.lawyer] = (bySrcLaw[s][c.lawyer]||0) + share;
    }
  }
  const sources = Object.keys(bySrcLaw);
  const datasets = LAWYERS.map(l => ({
    label:l, backgroundColor:COLORS[l],
    data: sources.map(s => bySrcLaw[s][l]||0)
  }));
  charts['chart-source-bar'] = new Chart(document.getElementById('chart-source-bar'), {
    type:'bar',
    data: { labels: sources, datasets },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{ x:{stacked:true}, y:{stacked:true, ticks:{callback:v=>fmt(v)}} },
      plugins:{ tooltip:{callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });
}

function renderSourceTable() {
  const cases = filteredCases(selectedYear);
  const agg = {};
  for (const c of cases) {
    const parts = splitSources(c.source);
    const share = c.amount / parts.length;
    for (const s of parts) {
      agg[s] = agg[s] || {count:0, amount:0};
      agg[s].count += 1; agg[s].amount += share;
    }
  }
  const entries = Object.entries(agg).sort((a,b)=>b[1].amount-a[1].amount);
  let html = `<thead><tr><th>來源</th><th class="num">案件數</th><th class="num">總金額</th><th class="num">平均/件</th><th class="num">占比</th></tr></thead><tbody>`;
  const totalAmt = entries.reduce((s,e)=>s+e[1].amount,0);
  for (const [s,d] of entries) {
    html += `<tr><td>${s}</td>
      <td class="num">${d.count}</td>
      <td class="num">$${fmt(d.amount)}</td>
      <td class="num">$${fmt(d.amount/d.count)}</td>
      <td class="num">${fmtPct(d.amount/totalAmt)}</td></tr>`;
  }
  document.getElementById('source-table').innerHTML = html + '</tbody>';
}

// ---- Tab 4: Drill ----
function renderDrillSelector() {
  const sel = document.getElementById('drill-lawyer');
  sel.innerHTML = LAWYERS.map(l=>`<option>${l}</option>`).join('');
  sel.value = drillLawyer;
  sel.onchange = () => { drillLawyer = sel.value; renderDrill(); };
}

function renderDrill() {
  const monthly = filteredMonthly(selectedYear).filter(m => m.lawyer === drillLawyer);
  const yms = monthly.map(m => `${m.year}/${String(m.month).padStart(2,'0')}`);

  const A = monthly.reduce((s,m)=>s+m.commission_A, 0);
  const selfA = monthly.reduce((s,m)=>s+m.self_A, 0);
  const zt = monthly.reduce((s,m)=>s+m.zhelu_total, 0);
  const lt = monthly.reduce((s,m)=>s+m.lawyer_total, 0);
  const procD = monthly.reduce((s,m)=>s+(m.proc_D||0), 0);
  const totalBase = A + selfA;
  const ratio = lt > 0 ? zt / lt : 0;
  const share = (zt + lt) > 0 ? zt / (zt + lt) * 100 : 0;
  const isJudicial = selectedCohort === 'judicial';

  // 拆分主案 vs 附屬收入
  //   主案 tier = 委任 B/C/E + 自案 + (senior) 諮詢成案/喆律轉案/法律010轉案
  //   附屬 tier = 諮詢費、介紹、追溯、受僱、續委、轉案、合作、其他、其他-自案、成案獎金
  const OWN_Z_TIERS = ['委任-引案(喆律)','委任-利潤(喆律)','自案(喆律)',
                       '諮詢成案(喆律)','喆律轉案(喆律)','法律010轉案(喆律)'];
  const OWN_L_TIERS = ['委任-咨詢(律師)','委任-利潤(律師)','自案(律師)',
                       '諮詢成案(律師)','喆律轉案(律師)','法律010轉案(律師)'];
  let ztOwn = 0, ltOwn = 0, ztMisc = 0, ltMisc = 0;
  const zMiscBreak = {};  // tier base name → amount
  const lMiscBreak = {};
  for (const m of monthly) {
    for (const [k, v] of Object.entries(m.tier || {})) {
      if (OWN_Z_TIERS.indexOf(k) !== -1) ztOwn += v;
      else if (OWN_L_TIERS.indexOf(k) !== -1) ltOwn += v;
      else if (k.endsWith('(喆律)')) {
        ztMisc += v;
        const base = k.replace('(喆律)', '');
        zMiscBreak[base] = (zMiscBreak[base] || 0) + v;
      } else {
        // 諮詢、成案獎金(律師)、介紹(律師)、追溯(律師) 等律師端附屬
        ltMisc += v;
        const base = k.replace('(律師)', '');
        lMiscBreak[base] = (lMiscBreak[base] || 0) + v;
      }
    }
  }
  // 附屬 tier 的 hover 解釋
  const TIER_TIP = {
    '諮詢': '諮詢費（100% 歸律師），通常 $2,000/場',
    '成案獎金': '諮詢律師後由他人承辦時，原諮詢律師抽 5% 獎金',
    '介紹': '律師介紹給他人承辦，取 10%（自然人）/ 20%（公司）佣金',
    '追溯': '過去介紹費事後補/扣的修正',
    '受僱': '律師替他人承辦的案件分潤',
    '續委': '舊客戶後續委任衍生的分潤',
    '轉案': '律師之間或與喆律之間的案件轉介分潤（非主案轉案）',
    '合作': '多律師合作案的分潤',
    '其他': '解析時未對上標準比例（左表非 0.7/0.6/1.0）的特殊案件',
    '其他-自案': '右表特殊比例案件（全庫僅 5 筆：4 筆 40% 含法扶舊案/退款等、1 筆 60% 特殊協議）'
  };
  // per-lawyer 特殊 tier 的細緻說明（覆蓋 global TIER_TIP）
  const perLawyerTips = (DATA.special_tier_tips && DATA.special_tier_tips[drillLawyer]) || {};
  function fmtBreak(obj) {
    const entries = Object.entries(obj).filter(([,v]) => Math.abs(v) > 0.5);
    entries.sort((a,b) => Math.abs(b[1]) - Math.abs(a[1]));
    return entries.map(([k,v]) => {
      const tip = perLawyerTips[k] || TIER_TIP[k] || '';
      const tipAttr = tip ? ` title="${tip.replace(/"/g, '&quot;').replace(/\n/g, '&#10;')}"` : '';
      const label = tip ? `<span style="text-decoration:underline dotted; cursor:help"${tipAttr}>${k}</span>` : k;
      return `${label} $${fmt(v)}`;
    }).join('、');
  }

  const dSubHtml = isJudicial
    ? `<br><span style="color:var(--orange)">處理費 D 扣除 $${fmt(procD)}（人事等共擔成本）</span><br><span style="color:var(--text-muted)" title="主案件金額 = 處理費 D + 喆律主案分潤 + 律師主案分潤">＝ D $${fmt(procD)} + 喆律主案 $${fmt(ztOwn)} + 律師主案 $${fmt(ltOwn)}</span>`
    : `<br><span style="color:var(--text-muted)">資深律師無共擔成本條款</span><br><span style="color:var(--text-muted)">＝ 喆律主案 $${fmt(ztOwn)} + 律師主案 $${fmt(ltOwn)}</span>`;
  const zMiscBreakStr = fmtBreak(zMiscBreak);
  const lMiscBreakStr = fmtBreak(lMiscBreak);
  const zMiscHtml = ztMisc > 0
    ? `主案 $${fmt(ztOwn)} + <span style="color:var(--orange)">附屬 $${fmt(ztMisc)}</span>${zMiscBreakStr ? `<br><span style="color:var(--text-muted);font-size:0.72rem">附屬明細：${zMiscBreakStr}</span>` : ''}`
    : `全部來自主案分潤`;
  const lMiscHtml = ltMisc > 0
    ? `主案 $${fmt(ltOwn)} + <span style="color:var(--orange)">附屬 $${fmt(ltMisc)}</span>${lMiscBreakStr ? `<br><span style="color:var(--text-muted);font-size:0.72rem">附屬明細：${lMiscBreakStr}</span>` : ''}`
    : `全部來自主案分潤`;

  document.getElementById('drill-kpi').innerHTML = `
    <div class="kpi">
      <div class="label">主案件金額</div>
      <div class="value">$${fmt(totalBase)}</div>
      <div class="sub">${monthly.length} 個月 · 委任 $${fmt(A)} ／ 自案 $${fmt(selfA)}${dSubHtml}</div>
    </div>
    <div class="kpi">
      <div class="label">喆律收入（全部 tier）</div>
      <div class="value" style="color:var(--gold)">$${fmt(zt)}</div>
      <div class="sub">${zMiscHtml}</div>
    </div>
    <div class="kpi">
      <div class="label">律師收入（全部 tier）</div>
      <div class="value" style="color:${COLORS[drillLawyer]||'#fff'}">$${fmt(lt)}</div>
      <div class="sub">${lMiscHtml}</div>
    </div>
    <div class="kpi">
      <div class="label">喆律佔比</div>
      <div class="value">${share.toFixed(1)}%</div>
      <div class="sub">喆律 ÷（喆律 + 律師）· 收入比 ${ratio.toFixed(2)}</div>
    </div>`;

  const tierColors = {
    '諮詢':'#6aa9ff',
    '委任-引案(喆律)':'#f2b84b','委任-咨詢(律師)':'#6aa9ff',
    '委任-利潤(喆律)':'#ffa534','委任-利潤(律師)':'#4a90e2',
    '諮詢成案(喆律)':'#f2b84b','諮詢成案(律師)':'#5dd39e',
    '喆律轉案(喆律)':'#ff9f43','喆律轉案(律師)':'#4ecdc4',
    '法律010轉案(喆律)':'#6aa9ff','法律010轉案(律師)':'#b58bff',
    '自案(喆律)':'#e25a5a','自案(律師)':'#5dd39e',
    '成案獎金(律師)':'#b58bff',
    '介紹(律師)':'#b58bff','追溯(律師)':'#ff9f43','合作(喆律)':'#ff6b6b','合作(律師)':'#4ecdc4',
    '受僱(喆律)':'#ffa8a8','受僱(律師)':'#6dd5ed','續委(喆律)':'#ff9ff3','續委(律師)':'#feca57',
    '轉案(喆律)':'#d6a2e8','轉案(律師)':'#74b9ff',
    '其他(律師)':'#a0a5b2','其他(喆律)':'#8898aa',
    '其他-自案(喆律)':'#a0a5b2','其他-自案(律師)':'#c9a06b',
  };
  const allTiers = new Set();
  monthly.forEach(m => Object.keys(m.tier).forEach(k => allTiers.add(k)));
  const zhelu_tiers = [...allTiers].filter(k => k.includes('(喆律)'));
  const lawyer_tiers = [...allTiers].filter(k => k.includes('(律師)') || k === '諮詢');

  function buildDS(tiers) {
    return tiers.map(t => ({
      label:t,
      backgroundColor: tierColors[t] || '#888',
      data: monthly.map(m => m.tier[t] || 0)
    }));
  }

  destroyChart('chart-drill-tier-z');
  charts['chart-drill-tier-z'] = new Chart(document.getElementById('chart-drill-tier-z'), {
    type:'bar',
    data: { labels: yms, datasets: buildDS(zhelu_tiers) },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{x:{stacked:true}, y:{stacked:true, ticks:{callback:v=>fmt(v)}}},
      plugins:{ tooltip:{callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });

  destroyChart('chart-drill-tier-l');
  charts['chart-drill-tier-l'] = new Chart(document.getElementById('chart-drill-tier-l'), {
    type:'bar',
    data: { labels: yms, datasets: buildDS(lawyer_tiers) },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{x:{stacked:true}, y:{stacked:true, ticks:{callback:v=>fmt(v)}}},
      plugins:{ tooltip:{callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });

}

// ---- Tab 5: Repeat clients (unified repeat_entries) ----
function filteredRepeatEntries(year) {
  const arr = DATA.repeat_entries || [];
  return year === 'all' ? arr : arr.filter(e => e.year === year);
}

function renderRepeatRule() {
  const cfg = DATA.repeat_config;
  if (!cfg) return;
  document.getElementById('repeat-rule-title').textContent = cfg.title;
  document.getElementById('repeat-rule-body').innerHTML =
    cfg.rule_html +
    '<br><span style="color:var(--fg-dim); font-size:12px">⚠ 資料限制：' +
    '律師加入前的舊客可能被誤判為「首委」；' +
    '金額 ≤ 2000 的純諮詢案已排除。</span>';
}

function renderRepeatKPI() {
  const cfg = DATA.repeat_config;
  if (!cfg) return;
  const es = filteredRepeatEntries(selectedYear);
  let total = 0, first = 0, in1y = 0, over1y = 0;
  let cur_sum = 0, new_sum = 0, moved_amt = 0;
  for (const e of es) {
    total += e.case_amount;
    if (e.classification === '首委') first += e.case_amount;
    else if (e.classification === '1年內續委') in1y += e.case_amount;
    else if (e.classification === '1年外續委') over1y += e.case_amount;
    cur_sum += e.cur_zhelu;
    new_sum += e.new_zhelu;
    if (e.new_zhelu !== e.cur_zhelu) moved_amt += e.case_amount;
  }
  const diff = new_sum - cur_sum;
  const gains = cfg.direction === 'zhelu_gains';
  const moved_pct = total > 0 ? moved_amt / total * 100 : 0;
  const zhelu_color = diff >= 0 ? 'var(--green)' : 'var(--red)';
  const lawyer_color = diff >= 0 ? 'var(--red)' : 'var(--green)';
  const absDiff = Math.abs(diff);
  const zhelu_sign = diff >= 0 ? '+' : '-';
  const lawyer_sign = diff >= 0 ? '-' : '+';

  document.getElementById('repeat-kpi').innerHTML = `
    <div class="kpi">
      <div class="label">當期案件總額</div>
      <div class="value">$${fmt(total)}</div>
      <div class="sub">${es.length} 筆分潤記錄</div>
    </div>
    <div class="kpi">
      <div class="label">${cfg.kpi_labels.moved_bucket_name}</div>
      <div class="value" style="color:#b58bff">$${fmt(moved_amt)}</div>
      <div class="sub">佔總額 ${moved_pct.toFixed(1)}%</div>
    </div>
    <div class="kpi">
      <div class="label">${cfg.kpi_labels.zhelu_impact_label}</div>
      <div class="value" style="color:${zhelu_color}">${zhelu_sign}$${fmt(absDiff)}</div>
      <div class="sub">現制 $${fmt(cur_sum)} → 新制 $${fmt(new_sum)}</div>
    </div>
    <div class="kpi">
      <div class="label">${cfg.kpi_labels.lawyer_impact_label}</div>
      <div class="value" style="color:${lawyer_color}">${lawyer_sign}$${fmt(absDiff)}</div>
      <div class="sub">等額轉移（律師 ↔ 喆律）</div>
    </div>`;
}

function renderRepeatStack() {
  destroyChart('chart-repeat-stack');
  const es = filteredRepeatEntries(selectedYear);
  const cats = ['首委','1年內續委','1年外續委'];
  const catColors = {'首委':'#6aa9ff','1年內續委':'#5dd39e','1年外續委':'#b58bff'};
  const data = {};
  for (const l of LAWYERS) data[l] = {'首委':0,'1年內續委':0,'1年外續委':0};
  for (const e of es) {
    if (!data[e.lawyer]) continue;
    if (cats.includes(e.classification)) data[e.lawyer][e.classification] += e.case_amount;
  }
  charts['chart-repeat-stack'] = new Chart(document.getElementById('chart-repeat-stack'), {
    type:'bar',
    data: {
      labels: LAWYERS,
      datasets: cats.map(cat => ({
        label: cat,
        backgroundColor: catColors[cat],
        data: LAWYERS.map(l => data[l][cat])
      }))
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{ x:{stacked:true}, y:{stacked:true, ticks:{callback:v=>fmt(v)}} },
      plugins:{ tooltip:{callbacks:{label:c=>`${c.dataset.label}: $${fmt(c.parsed.y)}`}} }
    }
  });
}

function renderRepeatHist() {
  destroyChart('chart-repeat-hist');
  const es = filteredRepeatEntries(selectedYear).filter(e => e.classification !== '首委' && e.days_since_first != null);
  const buckets = [
    {label:'0-90天', max:90, color:'#5dd39e'},
    {label:'91-180天', max:180, color:'#5dd39e'},
    {label:'181-365天', max:365, color:'#5dd39e'},
    {label:'366-540天', max:540, color:'#b58bff'},
    {label:'541-730天', max:730, color:'#b58bff'},
    {label:'>730天', max:Infinity, color:'#b58bff'},
  ];
  const counts = buckets.map(()=>0);
  const amounts = buckets.map(()=>0);
  for (const entry of es) {
    for (let i=0; i<buckets.length; i++) {
      if (entry.days_since_first <= buckets[i].max) {
        counts[i] += 1;
        amounts[i] += entry.case_amount;
        break;
      }
    }
  }
  charts['chart-repeat-hist'] = new Chart(document.getElementById('chart-repeat-hist'), {
    type:'bar',
    data: {
      labels: buckets.map(b=>b.label),
      datasets: [{
        label: '金額',
        backgroundColor: buckets.map(b=>b.color),
        data: amounts,
      }]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      scales:{ y:{ticks:{callback:v=>fmt(v)}} },
      plugins:{
        legend:{display:false},
        tooltip:{callbacks:{
          label:c=>{
            const i = c.dataIndex;
            return `${buckets[i].label}: $${fmt(amounts[i])} / ${counts[i]} 筆`;
          }
        }}
      }
    }
  });
}

function renderRepeatTable() {
  const cfg = DATA.repeat_config;
  if (!cfg) return;
  const es = filteredRepeatEntries(selectedYear);
  const agg = {};
  for (const l of LAWYERS) agg[l] = {total:0, first:0, in1y:0, over1y:0, cur:0, neu:0, cnt:0};
  for (const entry of es) {
    if (!agg[entry.lawyer]) continue;
    const a = agg[entry.lawyer];
    a.total += entry.case_amount; a.cnt += 1;
    if (entry.classification === '首委') a.first += entry.case_amount;
    else if (entry.classification === '1年內續委') a.in1y += entry.case_amount;
    else if (entry.classification === '1年外續委') a.over1y += entry.case_amount;
    a.cur += entry.cur_zhelu;
    a.neu += entry.new_zhelu;
  }
  const L = cfg.kpi_labels;
  let html = `<thead><tr>
    <th>律師</th><th class="num">筆數</th><th class="num">案件總額</th>
    <th class="num">首委</th><th class="num">1 年內</th><th class="num">1 年外</th>
    <th class="num">1 年外%</th>
    <th class="num">${L.table_col_cur}</th><th class="num">${L.table_col_new}</th><th class="num">${L.table_col_diff}</th>
  </tr></thead><tbody>`;
  let tT=0,tF=0,tI=0,tO=0,tCur=0,tNew=0;
  for (const l of LAWYERS) {
    const d = agg[l];
    const diff = d.neu - d.cur;
    const pct = d.total>0 ? d.over1y/d.total*100 : 0;
    const diffColor = diff > 0 ? 'var(--green)' : (diff < 0 ? 'var(--red)' : 'var(--fg-dim)');
    const diffSign = diff >= 0 ? '+' : '-';
    const canExpand = Math.abs(diff) > 0;
    const clickAttr = canExpand ? `class="num diff-cell" style="color:${diffColor}" data-lawyer="${l}" onclick="toggleRepeatDetail(this)"` : `class="num" style="color:${diffColor}"`;
    html += `<tr>
      <td><span class="lawyer-dot" style="background:${COLORS[l]}"></span>${l}</td>
      <td class="num">${d.cnt}</td>
      <td class="num">$${fmt(d.total)}</td>
      <td class="num">$${fmt(d.first)}</td>
      <td class="num" style="color:var(--green)">$${fmt(d.in1y)}</td>
      <td class="num" style="color:#b58bff">$${fmt(d.over1y)}</td>
      <td class="num">${pct.toFixed(1)}%</td>
      <td class="num">$${fmt(d.cur)}</td>
      <td class="num">$${fmt(d.neu)}</td>
      <td ${clickAttr}>${diffSign}$${fmt(Math.abs(diff))}${canExpand?' ▾':''}</td>
    </tr>
    <tr class="detail-row" data-lawyer-detail="${l}" style="display:none"><td colspan="10"></td></tr>`;
    tT+=d.total; tF+=d.first; tI+=d.in1y; tO+=d.over1y; tCur+=d.cur; tNew+=d.neu;
  }
  const tDiff = tNew - tCur;
  const tDiffColor = tDiff > 0 ? 'var(--green)' : (tDiff < 0 ? 'var(--red)' : 'var(--fg-dim)');
  const tDiffSign = tDiff >= 0 ? '+' : '-';
  const totalClickable = Math.abs(tDiff) > 0;
  const totalClickAttr = totalClickable ? `class="num diff-cell" style="color:${tDiffColor}" data-lawyer="__ALL__" onclick="toggleRepeatDetail(this)"` : `class="num" style="color:${tDiffColor}"`;
  html += `<tr style="border-top:2px solid var(--line);font-weight:600">
    <td>合計</td><td class="num"></td>
    <td class="num">$${fmt(tT)}</td>
    <td class="num">$${fmt(tF)}</td>
    <td class="num" style="color:var(--green)">$${fmt(tI)}</td>
    <td class="num" style="color:#b58bff">$${fmt(tO)}</td>
    <td class="num">${tT>0?(tO/tT*100).toFixed(1):0}%</td>
    <td class="num">$${fmt(tCur)}</td>
    <td class="num">$${fmt(tNew)}</td>
    <td ${totalClickAttr}>${tDiffSign}$${fmt(Math.abs(tDiff))}${totalClickable?' ▾':''}</td>
  </tr>
  <tr class="detail-row" data-lawyer-detail="__ALL__" style="display:none"><td colspan="10"></td></tr>`;
  document.getElementById('repeat-comparison-table').innerHTML = html + '</tbody>';
}

function toggleRepeatDetail(cell) {
  const lawyer = cell.dataset.lawyer;
  const detailRow = document.querySelector(`.detail-row[data-lawyer-detail="${lawyer}"]`);
  if (!detailRow) return;
  const isHidden = detailRow.style.display === 'none';
  // close all others first
  document.querySelectorAll('.detail-row').forEach(r => r.style.display = 'none');
  document.querySelectorAll('.diff-cell').forEach(c => {
    const t = c.textContent;
    if (t.endsWith(' ▴')) c.textContent = t.slice(0, -2) + ' ▾';
  });
  if (!isHidden) return;
  detailRow.style.display = '';
  cell.textContent = cell.textContent.replace(' ▾', ' ▴');
  // build content
  const es = filteredRepeatEntries(selectedYear)
    .filter(e => e.new_zhelu !== e.cur_zhelu && (lawyer === '__ALL__' || e.lawyer === lawyer))
    .sort((a, b) => Math.abs(b.new_zhelu - b.cur_zhelu) - Math.abs(a.new_zhelu - a.cur_zhelu));
  const td = detailRow.querySelector('td');
  if (es.length === 0) {
    td.innerHTML = `<div style="color:var(--fg-dim); padding:10px">無受影響案件</div>`;
    return;
  }
  let body = `<div style="font-size:12px; color:var(--fg-dim); margin-bottom:6px">
    ${lawyer === '__ALL__' ? '全部受影響案件' : lawyer + ' 受影響案件'} · 
    共 ${es.length} 筆 · 按差額降序
  </div>
  <table><thead><tr>
    ${lawyer === '__ALL__' ? '<th>律師</th>' : ''}
    <th>當事人</th><th>tier</th><th>分類</th>
    <th>首委日</th><th>本案日</th><th class="num">間隔天</th>
    <th class="num">金額</th><th class="num">現制喆律</th><th class="num">新制喆律</th><th class="num">差額</th>
  </tr></thead><tbody>`;
  for (const entry of es) {
    const d = entry.new_zhelu - entry.cur_zhelu;
    const dColor = d > 0 ? 'var(--green)' : 'var(--red)';
    const dSign = d >= 0 ? '+' : '-';
    body += `<tr>
      ${lawyer === '__ALL__' ? `<td><span class="lawyer-dot" style="background:${COLORS[entry.lawyer]}"></span>${entry.lawyer}</td>` : ''}
      <td>${entry.client||''}</td>
      <td>${entry.tier||''}</td>
      <td>${entry.classification||''}</td>
      <td>${entry.first_date||''}</td>
      <td>${entry.year}/${String(entry.month).padStart(2,'0')}</td>
      <td class="num">${entry.days_since_first != null ? entry.days_since_first : ''}</td>
      <td class="num">$${fmt(entry.case_amount)}</td>
      <td class="num">$${fmt(entry.cur_zhelu)}</td>
      <td class="num" style="color:var(--gold)">$${fmt(entry.new_zhelu)}</td>
      <td class="num" style="color:${dColor}">${dSign}$${fmt(Math.abs(d))}</td>
    </tr>`;
  }
  td.innerHTML = body + '</tbody></table>';
}

function renderRepeatMoved() {
  const cfg = DATA.repeat_config;
  if (!cfg) return;
  const gains = cfg.direction === 'zhelu_gains';
  const titleEl = document.getElementById('repeat-moved-title');
  if (titleEl) {
    titleEl.textContent = gains
      ? '新制下從自案提為諮詢成案的案件（上限 50 筆）'
      : '新制下重新歸類為律師自案的案件（上限 50 筆）';
  }
  const es = filteredRepeatEntries(selectedYear)
    .filter(entry => entry.new_zhelu !== entry.cur_zhelu)
    .sort((a,b) => b.case_amount - a.case_amount)
    .slice(0, 50);
  let html = `<thead><tr>
    <th>律師</th><th>當事人</th><th>tier</th><th>首委日</th><th>本案日</th>
    <th class="num">間隔天</th><th class="num">金額</th><th class="num">現制喆律</th><th class="num">新制喆律</th>
  </tr></thead><tbody>`;
  if (es.length === 0) {
    html += `<tr><td colspan="9" style="text-align:center; color:var(--fg-dim); padding:20px">當期無受影響案件</td></tr>`;
  }
  for (const entry of es) {
    html += `<tr>
      <td><span class="lawyer-dot" style="background:${COLORS[entry.lawyer]}"></span>${entry.lawyer}</td>
      <td>${entry.client||''}</td>
      <td>${entry.tier||''}</td>
      <td>${entry.first_date||''}</td>
      <td>${entry.year}/${String(entry.month).padStart(2,'0')}</td>
      <td class="num">${entry.days_since_first||''}</td>
      <td class="num">$${fmt(entry.case_amount)}</td>
      <td class="num">$${fmt(entry.cur_zhelu)}</td>
      <td class="num" style="color:var(--gold)">$${fmt(entry.new_zhelu)}</td>
    </tr>`;
  }
  document.getElementById('repeat-moved-cases').innerHTML = html + '</tbody>';
}

// ---- tier 類型說明 toggle ----
(function(){
  var btn = document.getElementById('tier-def-toggle');
  if (!btn) return;
  btn.addEventListener('click', function() {
    var p = document.getElementById('tier-def-panel');
    var open = p.style.display !== 'none';
    p.style.display = open ? 'none' : 'block';
    btn.textContent = open ? 'tier 類型說明 \u25be' : 'tier 類型說明 \u25b4';
    // 展開時 scroll 讓 panel 可見
    if (!open) setTimeout(function(){ p.scrollIntoView({behavior:'smooth', block:'nearest'}); }, 50);
  });
})();

// ---- tabs ----
document.querySelectorAll('.tab-btn').forEach(b => b.onclick = () => {
  if (b.classList.contains('hidden')) return;
  document.querySelectorAll('.tab-btn').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('page-'+b.dataset.tab).classList.add('active');
  renderAll();
});

// ---- init ----
function renderAll() {
  renderYearFilter();
  renderContractMatrix();
  renderKPI();
  renderMonthlyStacked('chart-monthly-zhelu', 'zhelu_total');
  renderMonthlyStacked('chart-monthly-lawyer', 'lawyer_total');
  renderZhelCompDoughnut();
  renderMarginBar();
  renderRadar();
  renderLineZhelu();
  renderKPITable();
  renderSourcePie();
  renderSourceBar();
  renderSourceTable();
  renderDrill();
  if (DATA.has_repeat_tab) {
    renderRepeatRule();
    renderRepeatKPI();
    renderRepeatStack();
    renderRepeatHist();
    renderRepeatTable();
    renderRepeatMoved();
  }
}
renderCohortPills();
updateTabVisibility();
renderDrillSelector();
selectedYear = '114';
renderAll();
</script>
</body>
</html>'''

out_html = HTML.replace('__DATA__', json.dumps(data, ensure_ascii=False))
(OUT/'dashboard.html').write_text(out_html, encoding='utf-8')
print(f'Wrote {OUT/"dashboard.html"} ({len(out_html):,} bytes)')
for ck, cv in data['cohorts'].items():
    print(f'  cohort={ck:10s}  lawyers={len(cv["lawyers"])}  monthly_rows={len(cv["monthly"])}  cases={len(cv["cases"])}')
print(f'Open with: start "" "{OUT/"dashboard.html"}"')
