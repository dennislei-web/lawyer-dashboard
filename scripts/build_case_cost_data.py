"""
案件成本 dashboard ETL — 產 public/finance/case-cost-data.json

包含：
  by_office[office]:
    monthly_series: 52 個月時間序列（薪資、案件量、單位月成本、進案/結案週期、lifetime 成本）
    age_distribution: 月度案件年齡桶分布 (timeline)
    case_type_breakdown: 案型 lifetime cost 排行（latest asof）
    lawyer_ranking / legal_staff_ranking: 個別 active inventory 排行
    office_breakdown: 各分所 lifetime cost（僅 '全所' 有）
  meta: 計算時點、口徑說明
  offices: ['全所', '台北所', ...]

口徑：
  全所:
    分子薪資 = 律師 + 法務 + 行政（排 010 + 金貝殼），全 dept
    分母案件 = 一般案件（排法顧 LA*），全 office
  個別所:
    分子薪資 = 該所對應 department 的薪資（跨所/共用 dept 不算）
    分母案件 = council_office_name == 該所 的一般案件
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

# Office → department mapping (薪資分子)
# 跨所共用 dept (其他/公司/法顧/None) 只在 '全所' 算
OFFICE_DEPTS = {
    '台北所': {'北所吉他', '北所(接案、行政、工讀)', '北所四部'},
    '桃園所': {'桃所'},
    '新竹所': {'竹所'},
    '台中所': {'中所'},
    '台南所': {'南所'},
    '高雄所': {'雄所'},
}
OFFICES_ORDERED = ['全所', '台北所', '桃園所', '新竹所', '台中所', '台南所', '高雄所']

# 律師權威名單 — 來自 zhelu.tw/about 官網（66 位）+ revenue dashboard WEBSITE_LAWYERS
# 不在這名單但出現在案件 5 個律師 role 的人 → 視為法務（同 revenue tab 邏輯）
# 也用來把 consultation_cases.lawyer_id 對應到 office 算 per-office booking
LAWYERS_BY_OFFICE = {
    '台北所': {
        '雷皓明','黃杰','孫少輔','許致維','劉明潔','方心瑜','張又仁','林桑羽','黃顯皓','柯雪莉',
        '陳寧馨','林昀','張嘉淳','黃世欣','李家泓','徐品軒','蘇萱','林宜嫻','吳柏慶','蕭予馨',
        '徐棠娜','劉誠夫','陳俊瑋','王怡婷','曾秉浩','李育哲','楊典翰','莊喬鈞','楊啓廷','張文祈',
        '劉庭懿','秦薇妮','黃庭汶','陳彥銘','陳昱璇','葉欣瑩','謝宗蓉','林敬修',
    },
    '桃園所': {'李杰峰','嚴心吟','張元毓','劉雅涵','李家徹','張佳榕','林品妘','王相為','王相爲'},
    '新竹所': {'陶光星','張家瑜','楊睿杰','葉芷羽'},
    '台中所': {'洪琬琪','李昭萱','許煜婕','陳璽仲','林佳穎','劉奕靖','李佳蓉','黃子菱'},
    '台南所': {'王湘閔','黃馨儀','黃書炫','姜奕成'},
    '高雄所': {'王郁萱','廖懿涵','陳映臻','蘇端雅'},
}
WEBSITE_LAWYERS = set().union(*LAWYERS_BY_OFFICE.values())
# 反向 map: name -> office
LAWYER_NAME_TO_OFFICE = {n: o for o, names in LAWYERS_BY_OFFICE.items() for n in names}

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

# 案型 normalize
SUBSTANTIVE_CASE_TYPES = [
    ('家事', ['家事', '離婚', '親權', '監護', '扶養', '配偶', '繼承', '遺產', '婚姻', '剩餘財產', '夫妻',
              '保護令', '通常保護令']),
    ('刑事', ['刑事', '毒品', '傷害', '詐欺', '竊盜', '妨害', '公然侮辱', '誹謗', '偽造', '違反',
              '誣告', '告訴', '偵查', '殺人', '搶奪', '強制', '校園霸凌', '少年保護']),
    ('簡易訴訟', ['支付命令', '本票', '律師函', '強制執行', '存證信函', '聲請', '催告',
                  '單次出庭', '陪同開庭', '陪同出席', '閱卷', '陳報', '書狀', '抗告', '聲明',
                  '律師代協商', '律師單次出庭']),
    ('民事一般', ['民事', '損害賠償', '債務', '契約', '租賃', '買賣', '返還', '清償', '借款', '侵害',
                  '協議書', '和解書', '和解協議', '調解', '車禍鑑定']),
    ('商務/勞資', ['公司', '股東', '勞資', '工資', '勞動', '公平交易', '性別平等', '法律意見書',
                   '常年法顧']),
    ('智財', ['智慧財產', '商標', '專利', '著作權']),
    ('行政/稅務', ['行政訴訟', '稅', '罰鍰', '訴願', '退學', '懲戒']),
    ('遺囑/其他文件', ['遺囑']),
]
PURE_CONSULT_CAUSES = {
    '現場諮詢', '視訊諮詢', '電話諮詢', '通話諮詢', '免費諮詢', '律師諮詢',
    '律師諮詢會議', '諮詢', '二次諮詢', '第二次現場諮詢', '現場(免費)諮詢',
}
CONSULT_KEYWORDS = ['現場諮詢', '視訊諮詢', '電話諮詢', '通話諮詢', '免費諮詢', '律師諮詢', '諮詢']

def classify_case_type(c):
    cause = (c.get('cause_of_action') or '').strip().rstrip('；;,、:: ').strip()
    sn = (c.get('serial_number') or '').upper()
    if sn.startswith('LA') or '法律顧問' in cause:
        return '法律顧問'
    if not cause:
        return '未分類'
    if cause in PURE_CONSULT_CAUSES:
        return '諮詢'
    for label, keys in SUBSTANTIVE_CASE_TYPES:
        for k in keys:
            if k in cause:
                return label
    for k in CONSULT_KEYWORDS:
        if k in cause:
            return '混合服務'
    return '其他'

def is_la(c):
    sn = (c.get('serial_number') or '').upper()
    return sn.startswith('LA') or '法律顧問' in (c.get('cause_of_action') or '')

print('=== Loading data ===')
fin_rows = fetch_all(f'{SB_URL}/finance_employees_monthly?select=fiscal_year,month,name,department,salary_subtotal')
print(f'  finance: {len(fin_rows)} rows')

case_cols = ('case_id,serial_number,aasm_state,'
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
    c['_office'] = c.get('council_office_name') or '(未標示)'

def state_at(c, asof, latest_asof=None):
    """
    回傳 case 在 asof 時的 state。
    對 latest_asof（==今天的 snapshot），改用 CRM 當下的 aasm_state field，
    避免 ghost-active（CRM appointed→unappointed transition 在 crm_cases schema 沒對應 column）。
    對 historical asof，best effort 用 transition timestamps 推。
    """
    if latest_asof is not None and asof == latest_asof:
        return c.get('aasm_state') or None
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

# Months
months = []
for fy in [111, 112, 113, 114, 115]:
    for m in range(1, 13):
        if fy == 115 and m > 4: break
        y = fy_to_year(fy)
        months.append((fy, m, month_start(y, m), month_end(y, m)))
LATEST_ASOF = months[-1][3]

# Salary aggregation: 全所 = 全部排 010；個別所 = OFFICE_DEPTS mapping
sal_all_by_mo = defaultdict(float)
sal_office_by_mo = {o: defaultdict(float) for o in OFFICE_DEPTS}
for r in fin_rows:
    dept = r.get('department')
    if dept in EXCLUDE_DEPTS_010: continue
    fm = (r['fiscal_year'], r['month'])
    amt = r['salary_subtotal'] or 0
    sal_all_by_mo[fm] += amt
    for off, depts in OFFICE_DEPTS.items():
        if dept in depts:
            sal_office_by_mo[off][fm] += amt

# Booking: 用 consultation_cases is_signed=true 的 revenue 加總 by case_date 月
# 全所 = 全部 signed booking；個別所 = lawyer_id 對應到該所的 booking
print('=== Loading consultation_cases for booking ===')
cons_rows = fetch_all(f'{SB_URL}/consultation_cases?select=case_date,is_signed,revenue,lawyer_id')
print(f'  consultation_cases: {len(cons_rows)} rows')

# lawyer_id -> name (從 lawyers 表)
print('  loading lawyers map...')
lawyer_rows = fetch_all(f'{SB_URL}/lawyers?select=id,name')
lawyer_id_to_name = {r['id']: r['name'] for r in lawyer_rows if r.get('id')}

booking_by_mo_all = defaultdict(float)
booking_by_mo_office = {o: defaultdict(float) for o in OFFICE_DEPTS}
unmapped_lawyer_ids = set()
for r in cons_rows:
    if not r.get('is_signed'): continue
    rev = r.get('revenue')
    if not rev: continue
    cd = r.get('case_date')
    if not cd: continue
    try:
        dt = datetime.fromisoformat(cd).date()
    except:
        continue
    fy = dt.year - 1911
    key = (fy, dt.month)
    amt = float(rev)
    booking_by_mo_all[key] += amt
    lid = r.get('lawyer_id')
    name = lawyer_id_to_name.get(lid) if lid else None
    off = LAWYER_NAME_TO_OFFICE.get(name) if name else None
    if off:
        booking_by_mo_office[off][key] += amt
    elif lid:
        unmapped_lawyer_ids.add(lid)
print(f'  booking signed: 全所 total {len(cons_rows)} rows; per-office mapped offices = {sum(1 for o in booking_by_mo_office if booking_by_mo_office[o])}; unmapped lawyer_id count = {len(unmapped_lawyer_ids)}')

def compute_office_slice(office, case_filter, sal_by_mo, booking_by_mo=None):
    """
    case_filter: callable(case) -> bool
    sal_by_mo: dict (fy, m) -> salary
    returns dict with monthly_series, age_distribution, case_type_breakdown, lawyer_ranking, legal_staff_ranking
    """
    general_subset = [c for c in general_cases if case_filter(c)]
    la_subset = [c for c in la_cases if case_filter(c)]

    monthly_series = []
    age_distribution = []
    for fy, m, mstart, asof in months:
        counts = {'pure_firm':0,'legal_staff_only':0,'pure_partner':0,'mixed':0,'no_one':0}
        la_active = 0
        active_durs = []
        age_buckets = {'<90':0, '90-365':0, '1-2yr':0, '>2yr':0}
        for c in general_subset:
            if state_at(c, asof, LATEST_ASOF) != 'appointed': continue
            ot = owner_type(c, asof)
            counts[ot] += 1
            if c['_created']:
                age = (asof - c['_created']).days
                active_durs.append(age)
                if age < 90: age_buckets['<90'] += 1
                elif age < 365: age_buckets['90-365'] += 1
                elif age < 730: age_buckets['1-2yr'] += 1
                else: age_buckets['>2yr'] += 1
        for c in la_subset:
            if state_at(c, asof, LATEST_ASOF) == 'appointed': la_active += 1

        closed_durs = []
        for c in general_subset:
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

        # 真實 P&L 比值 (flow/flow, 修正 stock-flow trap)
        new_booking = (booking_by_mo or {}).get((fy, m), 0)
        n_closed = len(closed_durs)
        sal_to_booking_pct = round(sal / new_booking * 100, 1) if new_booking else 0
        sal_per_closed_case = round(sal / n_closed) if n_closed else 0
        # 12 mo rolling 待後續迴圈外計算

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
            'new_booking': round(new_booking),
            'sal_to_booking_pct': sal_to_booking_pct,
            'sal_per_closed_case': sal_per_closed_case,
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

    # 12 個月 rolling average for sal_to_booking_pct + sal_per_closed_case (穩定化 monthly noise)
    for i in range(len(monthly_series)):
        window = monthly_series[max(0, i-11):i+1]
        sal_sum = sum(r['sal_office'] for r in window)
        booking_sum = sum(r['new_booking'] for r in window)
        closed_sum = sum(r['n_closed_in_month'] for r in window)
        monthly_series[i]['sal_to_booking_pct_12mo'] = round(sal_sum / booking_sum * 100, 1) if booking_sum else 0
        monthly_series[i]['sal_per_closed_case_12mo'] = round(sal_sum / closed_sum) if closed_sum else 0
        monthly_series[i]['new_booking_12mo'] = round(booking_sum)
        monthly_series[i]['n_closed_12mo'] = closed_sum

    # case_type / ranking 用 latest asof（最新月 / 各年的 year-end 由前端 derive）
    # 為了讓「年度」filter 在前端 zoom 後仍能拿到該年 asof 的 breakdown，
    # 改成預先算每個 fy 的 year-end asof 的 breakdown
    case_type_by_year = {}
    lawyer_by_year = {}
    legal_staff_by_year = {}

    def asof_for_year(fy):
        # 該 fy 在 months 中的最後一個 entry
        entries = [m_tuple for m_tuple in months if m_tuple[0] == fy]
        return entries[-1] if entries else None

    # 包含 'all' 和每個 fy 各一個 snapshot
    year_keys = ['all'] + sorted({m_tuple[0] for m_tuple in months})

    twelve_mo_window = lambda asof: (
        date(asof.year - 1, asof.month, 1) if asof.month > 1 else date(asof.year - 2, 12, 1),
        asof
    )

    for yk in year_keys:
        if yk == 'all':
            entry = months[-1]
        else:
            entry = asof_for_year(yk)
            if entry is None: continue
        fy_e, m_e, mstart_e, asof_e = entry
        tw_start, tw_end = twelve_mo_window(asof_e)
        latest_sal = sal_by_mo[(fy_e, m_e)]
        # latest u_firm = 該 asof 的 monthly_series u_firm
        # 找對應的 monthly entry
        ms_entry = next((x for x in monthly_series if x['fy_mo'] == f'{fy_e}-{m_e:02d}'), None)
        latest_u_firm = ms_entry['u_firm'] if ms_entry else 0

        # case type
        by_type = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[], 'pure_firm':0, 'partner':0})
        for c in general_subset:
            t = c['_case_type']
            if state_at(c, asof_e, LATEST_ASOF) == 'appointed':
                by_type[t]['active'] += 1
                ot = owner_type(c, asof_e)
                if ot in ('pure_firm','legal_staff_only'): by_type[t]['pure_firm'] += 1
                elif ot in ('pure_partner','mixed'): by_type[t]['partner'] += 1
            if c['_closed'] and tw_start <= c['_closed'] <= tw_end and c['_created']:
                by_type[t]['closed_in_12mo'] += 1
                by_type[t]['closed_durs'].append((c['_closed'] - c['_created']).days)

        type_rows = []
        for t, d in sorted(by_type.items(), key=lambda x: -x[1]['active']):
            cdur_med = statistics.median(d['closed_durs']) if d['closed_durs'] else 0
            cdur_mean = statistics.mean(d['closed_durs']) if d['closed_durs'] else 0
            lifetime = latest_u_firm * cdur_med / 30 if cdur_med else 0
            type_rows.append({
                'case_type': t,
                'active': d['active'],
                'pure_firm': d['pure_firm'],
                'partner': d['partner'],
                'closed_in_12mo': d['closed_in_12mo'],
                'closed_dur_median': round(cdur_med, 1),
                'closed_dur_mean': round(cdur_mean, 1),
                'lifetime_cost_per_case': round(lifetime),
            })
        case_type_by_year[str(yk)] = type_rows

        # ranking
        person_stats = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[],
                                            'is_partner':False, 'as_lawyer':False, 'as_legal_staff':False})
        for c in general_subset:
            s = state_at(c, asof_e, LATEST_ASOF)
            closed_this_year = c['_closed'] and tw_start <= c['_closed'] <= tw_end
            lawyer_role_names = set()
            for fld in LAWYER_ROLE_FIELDS:
                lawyer_role_names.update(parse_names(c.get(fld)))
            legal_staff_names = set(parse_names(c.get('assigned_members')))
            case_lawyers = (lawyer_role_names & WEBSITE_LAWYERS) - NON_CONSULTING_LAWYERS
            case_legal_staff = (legal_staff_names | (lawyer_role_names - WEBSITE_LAWYERS)) - NON_CONSULTING_LAWYERS - WEBSITE_LAWYERS

            for name in case_lawyers:
                person_stats[name]['as_lawyer'] = True
                if PARTNER_SINCE_DT.get(name) and PARTNER_SINCE_DT[name] <= asof_e:
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

        lawyer_by_year[str(yk)] = build_ranking('as_lawyer')
        legal_staff_by_year[str(yk)] = build_ranking('as_legal_staff')

    return {
        'monthly_series': monthly_series,
        'age_distribution': age_distribution,
        'case_type_by_year': case_type_by_year,
        'lawyer_by_year': lawyer_by_year,
        'legal_staff_by_year': legal_staff_by_year,
    }

# ============ Compute slices ============
by_office = {}
print('\n=== Computing 全所 ===')
by_office['全所'] = compute_office_slice('全所', lambda c: True, sal_all_by_mo, booking_by_mo_all)

for off in OFFICE_DEPTS:
    print(f'=== Computing {off} ===')
    by_office[off] = compute_office_slice(off, lambda c, o=off: c['_office'] == o, sal_office_by_mo[off], booking_by_mo_office[off])

# ============ Office breakdown (全所 only) — 各分所 lifetime cost ranking ============
print('\n=== Office breakdown ===')
latest_fy, latest_m, latest_start, latest_asof = months[-1]
twelve_mo_ago = date(latest_asof.year - 1, latest_asof.month, 1) if latest_asof.month > 1 else date(latest_asof.year - 2, 12, 1)
latest_u_firm_all = by_office['全所']['monthly_series'][-1]['u_firm']

by_office_agg = defaultdict(lambda: {'active':0, 'closed_in_12mo':0, 'closed_durs':[], 'pure_firm':0, 'partner':0})
for c in general_cases:
    o = c['_office']
    if state_at(c, latest_asof, LATEST_ASOF) == 'appointed':
        by_office_agg[o]['active'] += 1
        ot = owner_type(c, latest_asof)
        if ot in ('pure_firm','legal_staff_only'): by_office_agg[o]['pure_firm'] += 1
        elif ot in ('pure_partner','mixed'): by_office_agg[o]['partner'] += 1
    if c['_closed'] and twelve_mo_ago <= c['_closed'] <= latest_asof and c['_created']:
        by_office_agg[o]['closed_in_12mo'] += 1
        by_office_agg[o]['closed_durs'].append((c['_closed'] - c['_created']).days)

office_breakdown = []
for o, d in sorted(by_office_agg.items(), key=lambda x: -x[1]['active']):
    cdur_med = statistics.median(d['closed_durs']) if d['closed_durs'] else 0
    lifetime = latest_u_firm_all * cdur_med / 30 if cdur_med else 0
    office_breakdown.append({
        'office': o,
        'active': d['active'],
        'pure_firm': d['pure_firm'],
        'partner': d['partner'],
        'closed_in_12mo': d['closed_in_12mo'],
        'closed_dur_median': round(cdur_med, 1),
        'lifetime_cost_per_case': round(lifetime),
    })

# ============ Output ============
output = {
    'meta': {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'asof_date': latest_asof.isoformat(),
        'asof_fy_mo': f'{latest_fy}-{latest_m:02d}',
        '口徑': '分子薪資=律師+法務+行政（排010+金貝殼）; 分母案件=一般案件（排法顧）; 個別所薪資只算 OFFICE_DEPTS mapping，跨所/共用 dept 只在全所',
        'window': f'{months[0][0]}-{months[0][1]:02d} ~ {months[-1][0]}-{months[-1][1]:02d}',
        'fiscal_years': sorted({m_t[0] for m_t in months}),
    },
    'offices': OFFICES_ORDERED,
    'office_breakdown': office_breakdown,
    'by_office': by_office,
}

out_path = 'public/finance/case-cost-data.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

# Pretty preview
with open('scripts/_case_cost_preview.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'\nsaved: {out_path}')
for o in OFFICES_ORDERED:
    if o not in by_office: continue
    slc = by_office[o]
    last = slc['monthly_series'][-1]
    print(f'  {o:8} u_firm={last["u_firm"]:>6} active={last["firm"]+last["partner"]:>5}  case_types(all)={len(slc["case_type_by_year"].get("all",[]))}  lawyers(all)={len(slc["lawyer_by_year"].get("all",[]))}')
print(f'\nfile size: {os.path.getsize(out_path):,} bytes')
