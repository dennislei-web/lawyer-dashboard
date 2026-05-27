"""
案件成本 dashboard ETL — 產 public/finance/case-cost-data.json

包含：
  monthly_series: 52 個月時間序列（薪資、案件量、單位月成本、進案/結案週期、lifetime 成本）
  case_type_breakdown: 案型 lifetime cost 排行（當下 active）
  office_breakdown: 各 office 單位月成本 + lifetime cost
  lawyer_ranking: 律師個別 active inventory 排行
  age_distribution: 月度案件年齡桶分布 (timeline)
  meta: 計算時點、口徑說明

口徑：
  分子薪資 = 律師 + 法務 + 行政（排 010 + 金貝殼），不排雷皓明/黃杰
  分母案件 = 一般案件（排法顧 LA*）
  case lifetime cost = u_firm × 結案週期(月)
"""
import sys, io, os, urllib.request, json, statistics
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
load_dotenv('scripts/.env')
SB_URL = 'https://zpbkeyhxyykbvownrngf.supabase.co/rest/v1'
HEADERS = {'apikey': os.environ['SUPABASE_SERVICE_KEY'], 'Authorization': f'Bearer {os.environ["SUPABASE_SERVICE_KEY"]}'}

PARTNER_SINCE = {
    '孫少輔': '2023-11-01', '許致維': '2024-04-01', '劉明潔': '2025-07-01', '方心瑜': '2025-10-01',
    '陳璽仲': '2024-09-01', '許煜婕': '2024-11-01', '蕭予馨': '2025-01-01', '徐棠娜': '2025-02-01',
    '林昀': '2025-03-01', '李昭萱': '2025-06-01', '柯雪莉': '2025-09-01', '吳柏慶': '2026-03-01',
    '黃顯皓': '2025-10-01', '蘇萱': '2026-05-01', '黃世欣': '2020-01-01',
    '劉誠夫': '2023-11-01', '陳俊瑋': '2023-11-01', '曾秉浩': '2023-11-01',
}
PARTNER_SINCE_DT = {k: datetime.strptime(v, '%Y-%m-%d').date() for k, v in PARTNER_SINCE.items()}
EXCLUDE_DEPTS_010 = {'北所010', '北所金貝殼'}

# 律師權威名單 — 來自 zhelu.tw/about 官網（66 位）+ revenue dashboard WEBSITE_LAWYERS
# 不在這名單但出現在案件 5 個律師 role 的人 → 視為法務（同 revenue tab 邏輯）
WEBSITE_LAWYERS = {
    # 台北所 (38)
    '雷皓明','黃杰','孫少輔','許致維','劉明潔','方心瑜','張又仁','林桑羽','黃顯皓','柯雪莉',
    '陳寧馨','林昀','張嘉淳','黃世欣','李家泓','徐品軒','蘇萱','林宜嫻','吳柏慶','蕭予馨',
    '徐棠娜','劉誠夫','陳俊瑋','王怡婷','曾秉浩','李育哲','楊典翰','莊喬鈞','楊啓廷','張文祈',
    '劉庭懿','秦薇妮','黃庭汶','陳彥銘','陳昱璇','葉欣瑩','謝宗蓉','林敬修',
    # 桃園所 (8)
    '李杰峰','嚴心吟','張元毓','劉雅涵','李家徹','張佳榕','林品妘','王相為','王相爲',
    # 新竹所 (4)
    '陶光星','張家瑜','楊睿杰','葉芷羽',
    # 台中所 (8)
    '洪琬琪','李昭萱','許煜婕','陳璽仲','林佳穎','劉奕靖','李佳蓉','黃子菱',
    # 台南所 (4)
    '王湘閔','黃馨儀','黃書炫','姜奕成',
    # 高雄所 (4)
    '王郁萱','廖懿涵','陳映臻','蘇端雅',
}

# 非諮詢律師（不算辦案律師）
NON_CONSULTING_LAWYERS = {
    '張飛宇',  # 財務主管
}

def fy_to_year(fy): return fy + 1911
def month_end(y, m):
    if m == 12: return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)
def month_start(y, m): return date(y, m, 1)

def fetch_all(url):
    rows = []; offset = 0
    while True:
        u = f'{url}&limit=1000&offset={offset}'
        req = urllib.request.Request(u, headers=HEADERS)
        chunk = json.loads(urllib.request.urlopen(req).read())
        rows.extend(chunk)
        if len(chunk) < 1000: break
        offset += 1000
    return rows

def to_date(v):
    if not v: return None
    try: return datetime.fromisoformat(v.replace('Z','+00:00')).date()
    except: return None

def parse_names(field):
    if not field: return []
    if isinstance(field, list): return [str(x).strip() for x in field if x]
    if isinstance(field, str):
        try: return [str(x).strip() for x in json.loads(field) if x]
        except: return [field.strip()]
    return []

LAWYER_ROLE_FIELDS = ['council_lawyers','litigation_lawyers','in_court_lawyers','pleading_lawyers','complaint_lawyers']

# 案型 normalize — substantive case type 優先，諮詢只在 fallback 使用
# 邏輯：cause 中只要出現實質案型 keyword（家事/民事/刑事...）就用那個，
#       全部 miss 才看是否含「諮詢」keyword。這修正了「現場諮詢；離婚協議書」誤歸諮詢的問題。
SUBSTANTIVE_CASE_TYPES = [
    ('家事', ['家事', '離婚', '親權', '監護', '扶養', '配偶', '繼承', '遺產', '婚姻', '剩餘財產', '夫妻']),
    ('刑事', ['刑事', '毒品', '傷害', '詐欺', '竊盜', '妨害', '公然侮辱', '誹謗', '偽造', '違反',
              '誣告', '告訴', '偵查', '殺人', '搶奪', '強制']),
    ('簡易訴訟', ['支付命令', '本票', '律師函', '強制執行', '存證信函', '聲請', '催告']),
    ('民事一般', ['民事', '損害賠償', '債務', '契約', '租賃', '買賣', '返還', '清償', '借款', '侵害']),
    ('商務/勞資', ['公司', '股東', '勞資', '工資', '勞動']),
    ('智財', ['智慧財產', '商標', '專利', '著作權']),
    ('行政/稅務', ['行政訴訟', '稅', '罰鍰']),
]
CONSULT_KEYWORDS = ['現場諮詢', '視訊諮詢', '電話諮詢', '通話諮詢', '免費諮詢', '律師諮詢', '諮詢']

def classify_case_type(c):
    cause = (c.get('cause_of_action') or '').strip()
    sn = (c.get('serial_number') or '').upper()
    if sn.startswith('LA') or '法律顧問' in cause:
        return '法律顧問'
    if not cause:
        return '未分類'
    # Step 1: 找實質案型 keyword
    for label, keys in SUBSTANTIVE_CASE_TYPES:
        for k in keys:
            if k in cause:
                return label
    # Step 2: 全部 miss，才 fallback 諮詢
    for k in CONSULT_KEYWORDS:
        if k in cause:
            return '諮詢'
    return '其他'

def is_la(c):
    sn = (c.get('serial_number') or '').upper()
    return sn.startswith('LA') or '法律顧問' in (c.get('cause_of_action') or '')

print('=== Loading data ===')
fin_rows = fetch_all(f'{SB_URL}/finance_employees_monthly?select=fiscal_year,month,name,department,salary_subtotal')
print(f'  finance: {len(fin_rows)} rows')

case_cols = ('case_id,serial_number,'
             'council_lawyers,assigned_members,litigation_lawyers,in_court_lawyers,pleading_lawyers,complaint_lawyers,'
             'crm_created_at,appointed_at,closed_at,canceled_at,unconcluded_at,pending_at,'
             'cause_of_action,department_name,council_office_name')
cases = fetch_all(f'{SB_URL}/crm_cases?select={case_cols}')
print(f'  crm_cases: {len(cases)}')

general_cases = [c for c in cases if not is_la(c)]
la_cases = [c for c in cases if is_la(c)]
print(f'  general: {len(general_cases)}  法顧: {len(la_cases)}')

print('  preprocessing...')
for c in general_cases + la_cases:
    c['_created'] = to_date(c.get('crm_created_at'))
    c['_appointed'] = to_date(c.get('appointed_at'))
    c['_closed'] = to_date(c.get('closed_at'))
    c['_canceled'] = to_date(c.get('canceled_at'))
    c['_unconc'] = to_date(c.get('unconcluded_at'))
    c['_pending'] = to_date(c.get('pending_at'))
    handling = set()
    for fld in LAWYER_ROLE_FIELDS:
        handling.update(parse_names(c.get(fld)))
    legal_staff = set(parse_names(c.get('assigned_members')))
    c['_handling_lawyers'] = (handling - legal_staff) - NON_CONSULTING_LAWYERS
    c['_handling_all'] = (handling | legal_staff) - NON_CONSULTING_LAWYERS
    c['_legal_staff'] = legal_staff - NON_CONSULTING_LAWYERS
    c['_case_type'] = classify_case_type(c)

def state_at(c, asof):
    trans = []
    for fld, st in [('_appointed','appointed'),('_pending','pending'),('_closed','closed'),
                    ('_canceled','canceled'),('_unconc','unconcluded')]:
        v = c.get(fld)
        if v and v <= asof:
            trans.append((v, st))
    if not trans:
        if c['_created'] and c['_created'] <= asof: return 'unappointed'
        return None
    trans.sort()
    return trans[-1][1]

def owner_type(c, asof):
    if not c['_handling_all']: return 'no_one'
    if not c['_handling_lawyers']: return 'legal_staff_only'
    p = sum(1 for n in c['_handling_lawyers'] if PARTNER_SINCE_DT.get(n) and PARTNER_SINCE_DT[n] <= asof)
    f = len(c['_handling_lawyers']) - p
    if f == 0: return 'pure_partner'
    if p == 0: return 'pure_firm'
    return 'mixed'

# ============ Monthly series ============
months = []
for fy in [111, 112, 113, 114, 115]:
    for m in range(1, 13):
        if fy == 115 and m > 4: break
        y = fy_to_year(fy)
        months.append((fy, m, month_start(y, m), month_end(y, m)))

sal_by_mo = defaultdict(float)
for r in fin_rows:
    if r.get('department') in EXCLUDE_DEPTS_010: continue
    sal_by_mo[(r['fiscal_year'], r['month'])] += r['salary_subtotal'] or 0

print(f'\n=== Computing {len(months)} monthly snapshots ===')
monthly_series = []
age_distribution = []

for fy, m, mstart, asof in months:
    counts = {'pure_firm':0,'legal_staff_only':0,'pure_partner':0,'mixed':0,'no_one':0}
    la_active = 0
    active_durs = []
    age_buckets = {'<90':0, '90-365':0, '1-2yr':0, '>2yr':0}
    for c in general_cases:
        if state_at(c, asof) != 'appointed': continue
        ot = owner_type(c, asof)
        counts[ot] += 1
        if c['_created']:
            age = (asof - c['_created']).days
            active_durs.append(age)
            if age < 90: age_buckets['<90'] += 1
            elif age < 365: age_buckets['90-365'] += 1
            elif age < 730: age_buckets['1-2yr'] += 1
            else: age_buckets['>2yr'] += 1
    for c in la_cases:
        if state_at(c, asof) == 'appointed': la_active += 1

    closed_durs = []
    for c in general_cases:
        if c['_closed'] and mstart <= c['_closed'] <= asof and c['_created']:
            closed_durs.append((c['_closed'] - c['_created']).days)

    firm = counts['pure_firm'] + counts['legal_staff_only']
    part = counts['pure_partner'] + counts['mixed']
    lump = firm + part
    sal = sal_by_mo[(fy, m)]

    u_lump = sal/lump if lump else 0
    u_firm = sal/firm if firm else 0
    cdur_median = statistics.median(closed_durs) if closed_durs else 0
    cdur_mean = statistics.mean(closed_durs) if closed_durs else 0
    adur_median = statistics.median(active_durs) if active_durs else 0
    adur_mean = statistics.mean(active_durs) if active_durs else 0
    lifetime_cost_per_case = u_firm * cdur_median / 30 if cdur_median else 0

    monthly_series.append({
        'fy_mo': f'{fy}-{m:02d}',
        'real_date': asof.isoformat(),
        'sal_office': round(sal),
        'firm': firm, 'partner': part, 'lump': lump, 'la_active': la_active,
        'pure_firm': counts['pure_firm'],
        'legal_staff_only': counts['legal_staff_only'],
        'pure_partner': counts['pure_partner'],
        'mixed': counts['mixed'],
        'u_lump': round(u_lump),
        'u_firm': round(u_firm),
        'active_dur_median': round(adur_median, 1),
        'active_dur_mean': round(adur_mean, 1),
        'closed_dur_median': round(cdur_median, 1),
        'closed_dur_mean': round(cdur_mean, 1),
        'n_closed_in_month': len(closed_durs),
        'lifetime_cost_per_case': round(lifetime_cost_per_case),
    })
    age_distribution.append({
        'fy_mo': f'{fy}-{m:02d}',
        **age_buckets
    })

# ============ Case type breakdown — 用最近月 asof ============
latest_fy, latest_m, latest_start, latest_asof = months[-1]
latest_sal = sal_by_mo[(latest_fy, latest_m)]
print(f'\n=== Case type breakdown (asof {latest_asof}) ===')

by_type = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[], 'pure_firm':0, 'partner':0})
twelve_mo_ago = date(latest_asof.year - 1, latest_asof.month, 1) if latest_asof.month > 1 else date(latest_asof.year - 2, 12, 1)
for c in general_cases:
    t = c['_case_type']
    if state_at(c, latest_asof) == 'appointed':
        by_type[t]['active'] += 1
        ot = owner_type(c, latest_asof)
        if ot in ('pure_firm','legal_staff_only'): by_type[t]['pure_firm'] += 1
        elif ot in ('pure_partner','mixed'): by_type[t]['partner'] += 1
    if c['_closed'] and twelve_mo_ago <= c['_closed'] <= latest_asof and c['_created']:
        by_type[t]['closed_in_12mo'] += 1
        by_type[t]['closed_durs'].append((c['_closed'] - c['_created']).days)

latest_u_firm = monthly_series[-1]['u_firm']
case_type_breakdown = []
for t, d in sorted(by_type.items(), key=lambda x: -x[1]['active']):
    cdur_med = statistics.median(d['closed_durs']) if d['closed_durs'] else 0
    cdur_mean = statistics.mean(d['closed_durs']) if d['closed_durs'] else 0
    lifetime = latest_u_firm * cdur_med / 30 if cdur_med else 0
    case_type_breakdown.append({
        'case_type': t,
        'active': d['active'],
        'pure_firm': d['pure_firm'],
        'partner': d['partner'],
        'closed_in_12mo': d['closed_in_12mo'],
        'closed_dur_median': round(cdur_med, 1),
        'closed_dur_mean': round(cdur_mean, 1),
        'lifetime_cost_per_case': round(lifetime),
    })

# ============ Office breakdown ============
print(f'=== Office breakdown ===')
by_office = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[], 'pure_firm':0, 'partner':0})
for c in general_cases:
    o = c.get('council_office_name') or '(未標示)'
    if state_at(c, latest_asof) == 'appointed':
        by_office[o]['active'] += 1
        ot = owner_type(c, latest_asof)
        if ot in ('pure_firm','legal_staff_only'): by_office[o]['pure_firm'] += 1
        elif ot in ('pure_partner','mixed'): by_office[o]['partner'] += 1
    if c['_closed'] and twelve_mo_ago <= c['_closed'] <= latest_asof and c['_created']:
        by_office[o]['closed_in_12mo'] += 1
        by_office[o]['closed_durs'].append((c['_closed'] - c['_created']).days)

office_breakdown = []
for o, d in sorted(by_office.items(), key=lambda x: -x[1]['active']):
    cdur_med = statistics.median(d['closed_durs']) if d['closed_durs'] else 0
    lifetime = latest_u_firm * cdur_med / 30 if cdur_med else 0
    office_breakdown.append({
        'office': o,
        'active': d['active'],
        'pure_firm': d['pure_firm'],
        'partner': d['partner'],
        'closed_in_12mo': d['closed_in_12mo'],
        'closed_dur_median': round(cdur_med, 1),
        'lifetime_cost_per_case': round(lifetime),
    })

# ============ Lawyer / Legal staff ranking ============
# 律師排行：5 個 lawyer role 出現的人，且 name ∈ WEBSITE_LAWYERS（排除法務）
# 法務排行：assigned_members 出現的人 + 在 5 個 lawyer role 但不在 WEBSITE_LAWYERS 的人
print(f'=== Lawyer / Legal staff ranking ===')

person_stats = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[],
                                     'is_partner':False, 'as_lawyer':False, 'as_legal_staff':False})

for c in general_cases:
    s = state_at(c, latest_asof)
    closed_this_year = c['_closed'] and twelve_mo_ago <= c['_closed'] <= latest_asof

    # 5 個 lawyer role 取 union (含合署律師)
    lawyer_role_names = set()
    for fld in LAWYER_ROLE_FIELDS:
        lawyer_role_names.update(parse_names(c.get(fld)))
    legal_staff_names = set(parse_names(c.get('assigned_members')))

    # 律師 = lawyer role 名單 ∩ WEBSITE_LAWYERS（含合署）
    case_lawyers = (lawyer_role_names & WEBSITE_LAWYERS) - NON_CONSULTING_LAWYERS
    # 法務 = assigned_members + (lawyer role 但不在 WEBSITE_LAWYERS) − NON_CONSULTING
    case_legal_staff = (legal_staff_names | (lawyer_role_names - WEBSITE_LAWYERS)) - NON_CONSULTING_LAWYERS - WEBSITE_LAWYERS

    for name in case_lawyers:
        person_stats[name]['as_lawyer'] = True
        if PARTNER_SINCE_DT.get(name) and PARTNER_SINCE_DT[name] <= latest_asof:
            person_stats[name]['is_partner'] = True
        if s == 'appointed':
            person_stats[name]['active'] += 1
        if closed_this_year and c['_created']:
            person_stats[name]['closed_in_12mo'] += 1
            person_stats[name]['closed_durs'].append((c['_closed'] - c['_created']).days)
    for name in case_legal_staff:
        person_stats[name]['as_legal_staff'] = True
        if s == 'appointed':
            person_stats[name]['active'] += 1
        if closed_this_year and c['_created']:
            person_stats[name]['closed_in_12mo'] += 1
            person_stats[name]['closed_durs'].append((c['_closed'] - c['_created']).days)

def build_ranking(filter_role):
    out = []
    for name, d in person_stats.items():
        if not d[filter_role]: continue
        if d['active'] == 0 and d['closed_in_12mo'] == 0: continue
        cdur_med = statistics.median(d['closed_durs']) if d['closed_durs'] else 0
        out.append({
            'name': name,
            'is_partner': d['is_partner'],
            'active_inventory': d['active'],
            'closed_in_12mo': d['closed_in_12mo'],
            'closed_dur_median': round(cdur_med, 1),
            'backlog_ratio': round(d['active'] / d['closed_in_12mo'], 2) if d['closed_in_12mo'] else None,
        })
    out.sort(key=lambda x: -x['active_inventory'])
    return out

lawyer_ranking = build_ranking('as_lawyer')
legal_staff_ranking = build_ranking('as_legal_staff')

# ============ Output ============
output = {
    'meta': {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'asof_date': latest_asof.isoformat(),
        'asof_fy_mo': f'{latest_fy}-{latest_m:02d}',
        '口徑': '分子薪資 = 律師+法務+行政（排010+金貝殼）; 分母案件 = 一般案件（排法顧）; lifetime = u_firm × 結案週期(月)',
        'window': f'{months[0][0]}-{months[0][1]:02d} ~ {months[-1][0]}-{months[-1][1]:02d}',
    },
    'monthly_series': monthly_series,
    'age_distribution': age_distribution,
    'case_type_breakdown': case_type_breakdown,
    'office_breakdown': office_breakdown,
    'lawyer_ranking': lawyer_ranking,
    'legal_staff_ranking': legal_staff_ranking,
}

out_path = 'public/finance/case-cost-data.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

# Also pretty version for inspection
with open('scripts/_case_cost_preview.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'\nsaved: {out_path}')
print(f'  monthly_series: {len(monthly_series)} months')
print(f'  case_type_breakdown: {len(case_type_breakdown)} types')
print(f'  office_breakdown: {len(office_breakdown)} offices')
print(f'  lawyer_ranking: {len(lawyer_ranking)} lawyers (WEBSITE_LAWYERS 白名單)')
print(f'  legal_staff_ranking: {len(legal_staff_ranking)} legal staff')
print(f'  age_distribution: {len(age_distribution)} months')
print(f'\nfile size: {os.path.getsize(out_path):,} bytes')
