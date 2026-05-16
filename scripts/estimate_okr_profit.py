#!/usr/bin/env python3
"""
評估 2026 年度（民國 115）達成 OKR 後的事務所獲利。

公式：
  數字 A（已實現，1-4月）
    = KR1 實際營業額
    + 法顧實際現金流（CRM 所內 + 法顧對帳 − 退款）
    + 法 0 實際 × 0.35
    + 合署各律師喆律分得加總（zhelu_total）
    − 實際成本（finance_data data_type='actual', section='operating_expense'）

  數字 B（未實現，5-12月）
    = KR1 月目標 × 剩餘月數
    + 法顧月目標 × 剩餘月數
    + KR5 法0 月目標 × 0.35 × 剩餘月數
    + 合署 KR4 轉案月目標 × 歷史轉案喆律分得% × 剩餘月數
    + 合署 KR4 自案月目標 × 歷史自案喆律分得% × 剩餘月數
    − 月預算成本 × 剩餘月數

歷史口徑：過去 12 個月 (民國 114-05 ~ 115-04)。
"""

import os
import json
import re
import sys
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/projects/lawyer-dashboard/scripts/.env'))
SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://zpbkeyhxyykbvownrngf.supabase.co'
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
if not SERVICE_KEY:
    print('ERROR: SUPABASE_SERVICE_KEY missing in scripts/.env', file=sys.stderr)
    sys.exit(1)

H = {'apikey': SERVICE_KEY, 'Authorization': f'Bearer {SERVICE_KEY}'}

YEAR = 2026          # 西元
FISCAL = YEAR - 1911 # 民國 115
ELAPSED = int(os.environ.get('ELAPSED', '4'))
REMAIN = 12 - ELAPSED

KR1_TARGET = 1350   # 萬/月
KR3_TARGET = 158    # 萬/月
KR5_TARGET = 666    # 萬/月（法 0）
KR4_REF_TARGET = 280    # 萬/月（轉案）
KR4_SELF_TARGET = 138   # 萬/月（自案）

FA0_SHARE = 0.35

# ════════ Supabase helpers ════════
def fetch_all(table, params=None, page_size=1000):
    rows = []
    offset = 0
    while True:
        url = f'{SUPABASE_URL}/rest/v1/{table}'
        p = dict(params or {})
        p['limit'] = page_size
        p['offset'] = offset
        r = requests.get(url, headers=H, params=p, timeout=30)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


# ════════ partners embedded JSON ════════
def load_partners():
    with open('public/partners/index.html') as f:
        html = f.read()
    m = re.search(r'<script id="embedded-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    return json.loads(m.group(1))


# ════════ 合署分項統計 ════════
def commission_zhelu(tier):
    """轉案喆律分得 = 委任-引案(喆律) + 委任-利潤(喆律) + 成案獎金(喆律)（senior cohort）"""
    return sum(v or 0 for k, v in (tier or {}).items()
               if k in ('委任-引案(喆律)', '委任-利潤(喆律)',
                        '成案獎金(喆律)', '委任-咨詢(喆律)'))


def self_zhelu(tier):
    """自案喆律分得"""
    return (tier or {}).get('自案(喆律)', 0) or 0


def analyze_partners(pjson):
    cohorts = pjson.get('cohorts', {})
    # 1) 當年 (115) 已過 1-4 月：累計各律師 zhelu_total
    ytd_zhelu = 0
    ytd_commission_A = 0
    ytd_self_A = 0
    ytd_commission_zhelu = 0
    ytd_self_zhelu = 0

    # 2) 過去 12 個月 (114-05 ~ 115-04)：歷史比例
    hist_commission_A = 0
    hist_commission_zhelu = 0
    hist_self_A = 0
    hist_self_zhelu = 0

    for key in ('judicial', 'senior'):  # consult cohort 不算合署人數目標
        c = cohorts.get(key, {})
        for rec in c.get('monthly', []):
            yr = str(rec.get('year'))
            mo = int(rec.get('month'))
            commA = float(rec.get('commission_A') or 0)
            selfA = float(rec.get('self_A') or 0)
            zt = float(rec.get('zhelu_total') or 0)
            tier = rec.get('tier') or {}
            cz = commission_zhelu(tier)
            sz = self_zhelu(tier)

            # 當年 YTD (1-4月)
            if yr == str(FISCAL) and 1 <= mo <= ELAPSED:
                ytd_zhelu += zt
                ytd_commission_A += commA
                ytd_self_A += selfA
                ytd_commission_zhelu += cz
                ytd_self_zhelu += sz

            # 歷史 12 個月 = (114, 5-12) + (115, 1-4)
            in_hist = (yr == '114' and 5 <= mo <= 12) or (yr == '115' and 1 <= mo <= 4)
            if in_hist:
                hist_commission_A += commA
                hist_commission_zhelu += cz
                hist_self_A += selfA
                hist_self_zhelu += sz

    ratio_commission = (hist_commission_zhelu / hist_commission_A) if hist_commission_A else 0
    ratio_self = (hist_self_zhelu / hist_self_A) if hist_self_A else 0

    return {
        'ytd_zhelu_total': ytd_zhelu,
        'ytd_commission_A': ytd_commission_A,
        'ytd_self_A': ytd_self_A,
        'ytd_commission_zhelu': ytd_commission_zhelu,
        'ytd_self_zhelu': ytd_self_zhelu,
        'hist_commission_A': hist_commission_A,
        'hist_commission_zhelu': hist_commission_zhelu,
        'hist_self_A': hist_self_A,
        'hist_self_zhelu': hist_self_zhelu,
        'ratio_commission': ratio_commission,
        'ratio_self': ratio_self,
    }


# ════════ revenue_records / advisor / 法0 ════════
def normalize_name(name):
    return (name or '').strip()


def is_partner_record(r):
    grp = r.get('group_name') or ''
    return '合署' in grp


def fetch_advisor_clients():
    """法顧客戶集合 = advisor_cases.client_name + advisor_transactions.client_name"""
    names = set()
    for r in fetch_all('advisor_cases', {'select': 'client_name'}):
        n = normalize_name(r.get('client_name'))
        if n:
            names.add(n)
    return names


def analyze_revenue(year, elapsed):
    """1-elapsed 月：KR1 實際、法顧 CRM 所內、合署參考"""
    start = f'{year}-01-01'
    end = f'{year}-12-31'
    rows = fetch_all('revenue_records', {
        'select': 'record_date,amount,transaction_type,group_name,is_void,client_name',
        'record_date': f'gte.{start}',
        'is_void': 'eq.false',
    })
    rows = [r for r in rows if r.get('record_date') and r['record_date'] <= end]

    advisor_clients = fetch_advisor_clients()

    kr1_paid = 0
    kr1_refund = 0
    adv_paid = 0
    adv_refund = 0
    partner_net = 0

    for r in rows:
        rd = r['record_date']
        m = int(rd[5:7])
        if m > elapsed:
            continue
        amt = float(r.get('amount') or 0)
        tx = r.get('transaction_type')
        is_partner = is_partner_record(r)
        cname = normalize_name(r.get('client_name'))
        is_advisor = (not is_partner) and (cname in advisor_clients)
        if is_partner:
            if tx == 'PaymentTransaction':
                partner_net += amt
            elif tx == 'RefundTransaction':
                partner_net -= amt
            continue
        if is_advisor:
            if tx == 'PaymentTransaction':
                adv_paid += amt
            elif tx == 'RefundTransaction':
                adv_refund += amt
        else:
            if tx == 'PaymentTransaction':
                kr1_paid += amt
            elif tx == 'RefundTransaction':
                kr1_refund += amt

    return {
        'kr1_actual': kr1_paid - kr1_refund,
        'advisor_in_records': adv_paid - adv_refund,
        'partner_in_records': partner_net,
    }


def analyze_advisor_cash(year, elapsed, advisor_clients):
    """法顧儲值 (advisor_transactions) 累計 1-elapsed 月，僅算 advisor_clients 集合內"""
    start = f'{year}-01-01'
    rows = fetch_all('advisor_transactions', {
        'select': 'record_date,amount,is_void,client_name',
        'record_date': f'gte.{start}',
        'is_void': 'eq.false',
    })
    deposit = 0
    skipped_other = 0
    for r in rows:
        rd = r.get('record_date')
        if not rd:
            continue
        m = int(rd[5:7])
        if m > elapsed:
            continue
        cname = normalize_name(r.get('client_name'))
        amt = float(r.get('amount') or 0)
        if cname not in advisor_clients:
            skipped_other += amt
            continue
        deposit += amt
    return {'deposit': deposit, 'skipped': skipped_other, 'net': deposit}


def analyze_fa0(year, elapsed):
    rows = fetch_all('fact_010_monthly_team', {
        'select': 'year,month,total_revenue',
        'year': f'eq.{year}',
    })
    total = 0
    for r in rows:
        if int(r['month']) <= elapsed:
            total += float(r.get('total_revenue') or 0)
    return total


# ════════ 成本 ════════
def analyze_cost(fiscal, elapsed):
    """operating_expense: 已過月份用 actual，actual 缺的 fallback budget；未過月份用 budget"""
    rows = fetch_all('finance_data', {
        'select': 'amount,month,data_type,finance_categories(section,is_subtotal)',
        'fiscal_year': f'eq.{fiscal}',
    })
    actual_monthly = defaultdict(float)
    budget_monthly = defaultdict(float)
    for r in rows:
        cat = r.get('finance_categories') or {}
        if cat.get('section') != 'operating_expense':
            continue
        if cat.get('is_subtotal'):
            continue
        m = int(r.get('month') or 0)
        amt = float(r.get('amount') or 0)
        if r.get('data_type') == 'actual':
            actual_monthly[m] += amt
        elif r.get('data_type') == 'budget':
            budget_monthly[m] += amt

    # 已過月份：actual 優先，缺則 budget
    actual_ytd = 0
    cost_sources = {}  # debug 用
    for m in range(1, elapsed + 1):
        if actual_monthly.get(m):
            actual_ytd += actual_monthly[m]
            cost_sources[m] = ('actual', actual_monthly[m])
        else:
            actual_ytd += budget_monthly.get(m, 0)
            cost_sources[m] = ('budget(fallback)', budget_monthly.get(m, 0))

    budget_remain = sum(budget_monthly[m] for m in range(elapsed + 1, 13))
    return {
        'actual_ytd': actual_ytd,
        'budget_remain': budget_remain,
        'cost_sources': cost_sources,
        'actual_monthly': dict(actual_monthly),
        'budget_monthly': dict(budget_monthly),
    }


# ════════ 主流程 ════════
def main():
    print(f'═══ {YEAR} 年度（民國 {FISCAL}）OKR 達成後預估獲利 ═══')
    print(f'已過月份: 1-{ELAPSED} 月  /  剩餘: {ELAPSED+1}-12 月\n')

    print('[1/5] 載入 partners JSON ...')
    pjson = load_partners()
    p = analyze_partners(pjson)

    print('[2/5] revenue_records 分割 KR1 / 法顧 ...')
    rev = analyze_revenue(YEAR, ELAPSED)

    print('[3/5] advisor_transactions 法顧儲值 ...')
    advisor_clients = fetch_advisor_clients()
    adv = analyze_advisor_cash(YEAR, ELAPSED, advisor_clients)

    print('[4/5] fact_010_monthly_team 法 0 ...')
    fa0 = analyze_fa0(YEAR, ELAPSED)

    print('[5/5] finance_data 成本 ...')
    cost = analyze_cost(FISCAL, ELAPSED)

    # ─── 數字 A：已實現 ───
    kr1_a = rev['kr1_actual']
    advisor_cash_a = rev['advisor_in_records'] + adv['net']
    fa0_a = fa0 * FA0_SHARE
    partner_a = p['ytd_zhelu_total']
    actual_cost = cost['actual_ytd']
    A_revenue = kr1_a + advisor_cash_a + fa0_a + partner_a
    A_profit = A_revenue - actual_cost

    # ─── 數字 B：未實現（剩餘月份）───
    kr1_b = KR1_TARGET * 10000 * REMAIN
    advisor_b = KR3_TARGET * 10000 * REMAIN
    fa0_b = KR5_TARGET * 10000 * FA0_SHARE * REMAIN
    partner_b = (KR4_REF_TARGET * 10000 * p['ratio_commission'] +
                 KR4_SELF_TARGET * 10000 * p['ratio_self']) * REMAIN
    budget_cost = cost['budget_remain']
    B_revenue = kr1_b + advisor_b + fa0_b + partner_b
    B_profit = B_revenue - budget_cost

    fmt = lambda v: f'{v/10000:>12,.1f} 萬'

    print('\n────────── 數字 A：已實現獲利 (1-4月實際) ──────────')
    print(f'  KR1 喆律所內            {fmt(kr1_a)}')
    print(f'  法顧現金流              {fmt(advisor_cash_a)}'
          f'   (CRM所內 {rev["advisor_in_records"]/10000:.1f} + 儲值淨 {adv["net"]/10000:.1f})')
    print(f'  法 0 (×0.35)            {fmt(fa0_a)}'
          f'   (毛 {fa0/10000:.1f})')
    print(f'  合署各律師喆律分得      {fmt(partner_a)}'
          f'   (轉案 {p["ytd_commission_zhelu"]/10000:.1f} / 自案 {p["ytd_self_zhelu"]/10000:.1f} / 其他 {(partner_a - p["ytd_commission_zhelu"] - p["ytd_self_zhelu"])/10000:.1f})')
    print(f'  ─ 收入小計             {fmt(A_revenue)}')
    src = cost['cost_sources']
    src_desc = ' / '.join(f'{m}月={s[0]}' for m, s in sorted(src.items()))
    print(f'  − 實際成本              {fmt(actual_cost)}   ({src_desc})')
    print(f'  ═ 數字 A                {fmt(A_profit)}')

    print('\n────────── 數字 B：剩餘月份預估獲利 (5-12月) ──────────')
    print(f'  KR1 月目標 1,350×{REMAIN}    {fmt(kr1_b)}')
    print(f'  法顧月目標 158×{REMAIN}      {fmt(advisor_b)}')
    print(f'  法0 月目標 666×0.35×{REMAIN} {fmt(fa0_b)}')
    print(f'  合署 (轉案 {KR4_REF_TARGET}×{p["ratio_commission"]*100:.1f}% + 自案 {KR4_SELF_TARGET}×{p["ratio_self"]*100:.1f}%) ×{REMAIN}')
    print(f'    歷史轉案喆律分得%: {p["ratio_commission"]*100:.2f}% '
          f'(過去12月: 喆律 {p["hist_commission_zhelu"]/10000:.1f}萬 / 轉案總額 {p["hist_commission_A"]/10000:.1f}萬)')
    print(f'    歷史自案喆律分得%: {p["ratio_self"]*100:.2f}% '
          f'(過去12月: 喆律 {p["hist_self_zhelu"]/10000:.1f}萬 / 自案總額 {p["hist_self_A"]/10000:.1f}萬)')
    print(f'                          {fmt(partner_b)}')
    print(f'  ─ 收入小計             {fmt(B_revenue)}')
    print(f'  − 預算成本              {fmt(budget_cost)}')
    print(f'  ═ 數字 B                {fmt(B_profit)}')

    print('\n════════════════════════════════════════════')
    print(f'  全年合計 A + B          {fmt(A_profit + B_profit)}')
    print('════════════════════════════════════════════')


if __name__ == '__main__':
    main()
