#!/usr/bin/env python3
"""
對比 Excel「115年公司、事務所利潤明細」1-3 月 vs 儀表板資料源。
"""

import os
import json
import re
import sys
from collections import defaultdict

import requests
import openpyxl
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/projects/lawyer-dashboard/scripts/.env'))
SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://zpbkeyhxyykbvownrngf.supabase.co'
SK = os.environ['SUPABASE_SERVICE_KEY']
H = {'apikey': SK, 'Authorization': f'Bearer {SK}'}

EXCEL = '/Users/dennislei/Downloads/115年公司、事務所利潤明細.xlsx'
PARTNERS_HTML = '/Users/dennislei/projects/lawyer-dashboard/.claude/worktrees/eager-wiles-c87fc5/public/partners/index.html'
YEAR = 2026
FISCAL = 115
MONTHS = [1, 2, 3]


def fetch_all(table, params=None):
    rows = []; offset = 0
    while True:
        p = dict(params or {}); p['limit'] = 1000; p['offset'] = offset
        r = requests.get(f'{SUPABASE_URL}/rest/v1/{table}', headers=H, params=p, timeout=30)
        r.raise_for_status()
        b = r.json(); rows.extend(b)
        if len(b) < 1000: break
        offset += 1000
    return rows


# ─── Excel 解析 ───
def parse_excel():
    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    out = {}
    for m in MONTHS:
        sn = f'1150{m}'
        ws = wb[sn]
        rows = list(ws.iter_rows(values_only=True))
        d = defaultdict(list)
        for row in rows:
            for j, v in enumerate(row):
                if v is None or not isinstance(v, str): continue
                lab = v.strip()
                nxt = row[j+1] if j+1 < len(row) else None
                if isinstance(nxt, (int, float)):
                    d[lab].append(nxt)

        # 利潤行：取多次出現的 5 個（依 sheet 上下文順序：法0/喆律/公司/觀星/瑩魚/合併）
        profits = d.get('利潤', [])

        # 注意各 sheet 順序可能略不同。簡化：直接讀已知 label
        out[m] = {
            'fa0_revenue': d['法律010收入'][0] if d.get('法律010收入') else 0,
            'zhelu_revenue_pure': d['喆律收入'][0] if d.get('喆律收入') else 0,
            'partner_revenue': d['合署律師合作收入'][0] if d.get('合署律師合作收入') else 0,
            'other_revenue': sum(d.get('其他收入', [])),
            # 合併利潤 / 各業務體利潤要看順序
            # 從原始 sheet 看：
            #  - 法律010利潤 (左欄): profits[0]
            #  - 公司利潤: profits[1]
            #  - 合併利潤: profits[2]
            #  - 觀星利潤: profits[3]
            #  - 喆律利潤: profits[4]
            #  (3月 sheet 順序略不同，多了瑩魚 -952)
            'profits_raw': profits,
            'fa0_profit': d['法律010'][0] if d.get('法律010') else 0,
            'zhelu_profit': d['喆律'][0] if d.get('喆律') else 0,
            'company_profit': d['公司'][0] if d.get('公司') else 0,
            'expense_total': d['支出總計'][0] if d.get('支出總計') else 0,
            'all_subtotals': d.get('小計', []),  # debug
        }
    return out


# ─── 儀表板資料源 ───
def load_partners():
    with open(PARTNERS_HTML) as f:
        html = f.read()
    m = re.search(r'<script id="embedded-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    return json.loads(m.group(1))


def normalize_name(name):
    return (name or '').strip()


def fetch_advisor_clients():
    names = set()
    for r in fetch_all('advisor_cases', {'select': 'client_name'}):
        n = normalize_name(r.get('client_name'))
        if n: names.add(n)
    return names


def revenue_by_month(year, advisor_clients, months=(1,2,3)):
    start = f'{year}-01-01'
    rows = fetch_all('revenue_records', {
        'select': 'record_date,amount,transaction_type,group_name,client_name,firm_amount,attribution_basis',
        'record_date': f'gte.{start}',
        'is_void': 'eq.false',
    })
    bymo = defaultdict(lambda: {'kr1_paid':0,'kr1_refund':0,'adv_paid':0,'adv_refund':0,
                                 'partner_paid':0,'partner_refund':0,
                                 'partner_firm':0})
    for r in rows:
        if not r.get('record_date'): continue
        m = int(r['record_date'][5:7])
        if m not in months: continue
        amt = float(r.get('amount') or 0)
        tx = r.get('transaction_type')
        is_p = '合署' in (r.get('group_name') or '')
        cn = normalize_name(r.get('client_name'))
        is_a = (not is_p) and (cn in advisor_clients)
        b = bymo[m]
        if is_p:
            firm = float(r.get('firm_amount') or 0)
            if tx == 'PaymentTransaction':
                b['partner_paid'] += amt
                b['partner_firm'] += firm
            elif tx == 'RefundTransaction':
                b['partner_refund'] += amt
                b['partner_firm'] -= firm
        elif is_a:
            if tx == 'PaymentTransaction': b['adv_paid'] += amt
            elif tx == 'RefundTransaction': b['adv_refund'] += amt
        else:
            if tx == 'PaymentTransaction': b['kr1_paid'] += amt
            elif tx == 'RefundTransaction': b['kr1_refund'] += amt
    return dict(bymo)


def advisor_deposits_by_month(year, advisor_clients):
    start = f'{year}-01-01'
    rows = fetch_all('advisor_transactions', {
        'select': 'record_date,amount,client_name',
        'record_date': f'gte.{start}',
        'is_void': 'eq.false',
    })
    out = defaultdict(float)
    for r in rows:
        if not r.get('record_date'): continue
        m = int(r['record_date'][5:7])
        if m not in (1,2,3): continue
        cn = normalize_name(r.get('client_name'))
        if cn not in advisor_clients: continue
        out[m] += float(r.get('amount') or 0)
    return dict(out)


def fa0_by_month(year):
    rows = fetch_all('fact_010_monthly_team', {
        'select': 'year,month,total_revenue',
        'year': f'eq.{year}',
    })
    out = defaultdict(float)
    for r in rows:
        m = int(r['month'])
        if m in (1,2,3):
            out[m] += float(r.get('total_revenue') or 0)
    return dict(out)


EXCLUDE_TIERS = {'諮詢', '介紹', '追溯', '月固定費',
                 '成案獎金(喆律)', '成案獎金(律師)'}

# 「轉案」概念：承辦案件中由喆律端引案的部分
COMMISSION_TIERS = {
    '委任-引案(喆律)', '委任-利潤(喆律)', '委任-咨詢(喆律)',
    '諮詢成案(喆律)', '喆律轉案(喆律)', '法律010轉案(喆律)',
    '轉案(喆律)',
    '顯皓承辦(喆律)', '諮詢費(喆律)',
}
SELF_TIERS = {
    '自案(喆律)', '其他-自案(喆律)', '顯皓自案(喆律)',
}
OTHER_KEEP_TIERS = {  # 受僱/合作/其他 也算喆律可分得（雖然 senior「其他」變動大）
    '受僱(喆律)', '合作(喆律)', '其他(喆律)',
}


def partners_zhelu_by_month(pjson, cohorts_filter=('judicial','senior','consult')):
    out = defaultdict(lambda: {'total':0, 'comm_z':0, 'self_z':0, 'other_z':0,
                                'commission_A':0, 'self_A':0, 'excluded':0})
    cohorts = pjson.get('cohorts', {})
    for key in cohorts_filter:
        c = cohorts.get(key, {})
        for rec in c.get('monthly', []):
            if str(rec.get('year')) != '115': continue
            m = int(rec.get('month'))
            if m not in (1,2,3): continue
            tier = rec.get('tier') or {}
            commA = float(rec.get('commission_A') or 0)
            selfA = float(rec.get('self_A') or 0)
            b = out[m]
            b['commission_A'] += commA
            b['self_A'] += selfA
            for k, v in tier.items():
                v = float(v or 0)
                if k in EXCLUDE_TIERS:
                    b['excluded'] += v
                    continue
                # 只看 (喆律) 結尾的
                if not k.endswith('(喆律)'):
                    continue
                if k in COMMISSION_TIERS:
                    b['comm_z'] += v
                elif k in SELF_TIERS:
                    b['self_z'] += v
                elif k in OTHER_KEEP_TIERS:
                    b['other_z'] += v
                else:
                    # 未分類的喆律 tier
                    b['other_z'] += v
            b['total'] = b['comm_z'] + b['self_z'] + b['other_z']
    return dict(out)


def cost_by_month(fiscal):
    rows = fetch_all('finance_data', {
        'select': 'amount,month,data_type,finance_categories(section,is_subtotal)',
        'fiscal_year': f'eq.{fiscal}',
    })
    out = defaultdict(float)
    for r in rows:
        cat = r.get('finance_categories') or {}
        if cat.get('section') != 'operating_expense' or cat.get('is_subtotal'): continue
        m = int(r.get('month') or 0)
        if r['data_type'] != 'actual': continue
        if m in (1,2,3):
            out[m] += float(r.get('amount') or 0)
    return dict(out)


def fmt(v):
    if abs(v) >= 1e8: return f'{v/1e8:.2f} 億'
    return f'{v/1e4:>10,.1f} 萬'


def main():
    print('═══ Excel vs 儀表板資料對比 (115 年 1-3 月) ═══\n')

    excel = parse_excel()

    print('[載入] partners JSON ...')
    pjson = load_partners()
    print('[載入] advisor_clients ...')
    ac = fetch_advisor_clients()
    print('[載入] revenue_records ...')
    rev = revenue_by_month(YEAR, ac)
    print('[載入] advisor_transactions ...')
    dep = advisor_deposits_by_month(YEAR, ac)
    print('[載入] fact_010_monthly_team ...')
    fa0 = fa0_by_month(YEAR)
    print('[載入] partners zhelu (僅 judicial+senior，排除 consult) ...')
    p_z = partners_zhelu_by_month(pjson, cohorts_filter=('judicial','senior'))
    p_z_with_consult = partners_zhelu_by_month(pjson, cohorts_filter=('judicial','senior','consult'))
    print('[載入] finance_data ...')
    cost = cost_by_month(FISCAL)
    print()

    for m in MONTHS:
        ex = excel[m]
        rv = rev.get(m, {})
        kr1 = rv.get('kr1_paid',0) - rv.get('kr1_refund',0)
        adv_in = rv.get('adv_paid',0) - rv.get('adv_refund',0)
        adv_dep = dep.get(m, 0)
        adv_total = adv_in + adv_dep
        fa0m = fa0.get(m, 0)
        pm = p_z.get(m, {'total':0,'comm_z':0,'self_z':0,'other_z':0})
        cstm = cost.get(m, 0)

        print(f'──────────── {m} 月 ────────────')
        print(f'                                Excel              儀表板             差異')
        print(f'  喆律收入 (純)              {fmt(ex["zhelu_revenue_pure"]):>15}   KR1: {fmt(kr1):>15}   {fmt(ex["zhelu_revenue_pure"] - kr1)}')
        print(f'                              ↑ 含法顧嗎?         (KR1 已排除法顧 & 合署)')
        print(f'  +法顧 (儀表板拆出)           ─                   法顧現金 {fmt(adv_total):>10}')
        print(f'      KR1+法顧合計             ─                   {fmt(kr1 + adv_total):>15}   {fmt(ex["zhelu_revenue_pure"] - (kr1 + adv_total))}')
        print(f'  合署律師合作收入           {fmt(ex["partner_revenue"]):>15}   zhelu_total: {fmt(pm["total"]):>10}   {fmt(ex["partner_revenue"] - pm["total"])}')
        print(f'      其中 轉案喆律分得                              {fmt(pm["comm_z"])}')
        print(f'      其中 自案喆律分得                              {fmt(pm["self_z"])}')
        print(f'      其中 其他喆律分得                              {fmt(pm["other_z"])}')
        print(f'  其他收入                   {fmt(ex["other_revenue"]):>15}')
        print(f'  法律010 收入               {fmt(ex["fa0_revenue"]):>15}   毛 ×0.35: {fmt(fa0m*0.35):>10}   毛: {fmt(fa0m)}')
        print(f'  支出總計                   {fmt(ex["expense_total"]):>15}   operating_expense actual: {fmt(cstm):>10}   {fmt(ex["expense_total"] - cstm)}')
        print(f'  合併利潤 (Excel)           {fmt(sum([ex["fa0_profit"], ex["zhelu_profit"], ex["company_profit"]])):>15}')
        print()

    # ───── 1-3 月合計 ─────
    print('═══════════ 1-3 月合計 ═══════════')
    ex_zhelu_pure = sum(excel[m]['zhelu_revenue_pure'] for m in MONTHS)
    ex_partner_rev = sum(excel[m]['partner_revenue'] for m in MONTHS)
    ex_other_rev = sum(excel[m]['other_revenue'] for m in MONTHS)
    ex_fa0_rev = sum(excel[m]['fa0_revenue'] for m in MONTHS)
    ex_expense = sum(excel[m]['expense_total'] for m in MONTHS)
    ex_profit_merged = sum(excel[m]['fa0_profit'] + excel[m]['zhelu_profit'] + excel[m]['company_profit'] for m in MONTHS)
    # 觀星 / 瑩魚利潤忽略 (都 0 或極小)

    dash_kr1 = sum((rev.get(m,{}).get('kr1_paid',0) - rev.get(m,{}).get('kr1_refund',0)) for m in MONTHS)
    dash_adv = sum((rev.get(m,{}).get('adv_paid',0) - rev.get(m,{}).get('adv_refund',0)) + dep.get(m,0) for m in MONTHS)
    dash_fa0_gross = sum(fa0.get(m,0) for m in MONTHS)
    dash_fa0_share = dash_fa0_gross * 0.35
    dash_partner = sum(p_z.get(m,{}).get('total',0) for m in MONTHS)
    dash_partner_comm = sum(p_z.get(m,{}).get('comm_z',0) for m in MONTHS)
    dash_partner_self = sum(p_z.get(m,{}).get('self_z',0) for m in MONTHS)
    dash_partner_other = sum(p_z.get(m,{}).get('other_z',0) for m in MONTHS)
    dash_partner_with_consult = sum(p_z_with_consult.get(m,{}).get('total',0) for m in MONTHS)
    consult_only = dash_partner_with_consult - dash_partner
    # revenue_records 口徑（會計帳）
    rev_partner_amt = sum((rev.get(m,{}).get('partner_paid',0) - rev.get(m,{}).get('partner_refund',0)) for m in MONTHS)
    rev_partner_firm = sum(rev.get(m,{}).get('partner_firm',0) for m in MONTHS)
    dash_cost = sum(cost.get(m,0) for m in MONTHS)

    dash_revenue = dash_kr1 + dash_adv + dash_fa0_share + dash_partner
    dash_profit = dash_revenue - dash_cost

    print(f'\n  項目                       Excel              儀表板         差異')
    print(f'  ─────────────────────────────────────────────────────────────')
    print(f'  喆律純收入                 {fmt(ex_zhelu_pure):>15}   KR1: {fmt(dash_kr1):>15}   {fmt(ex_zhelu_pure - dash_kr1)}')
    print(f'  (Excel 喆律純收入是否含法顧?)')
    print(f'     法顧現金流                ─                   {fmt(dash_adv):>15}')
    print(f'     KR1 + 法顧                ─                   {fmt(dash_kr1 + dash_adv):>15}   {fmt(ex_zhelu_pure - dash_kr1 - dash_adv)}')
    print(f'  合署合作收入               {fmt(ex_partner_rev):>15}   {fmt(dash_partner):>15}   {fmt(ex_partner_rev - dash_partner)}')
    print(f'     轉案 z (judicial+senior)                         {fmt(dash_partner_comm):>15}')
    print(f'     自案 z                                          {fmt(dash_partner_self):>15}')
    print(f'     其他 z                                          {fmt(dash_partner_other):>15}')
    print(f'     (若含 consult 黃顯皓: +{fmt(consult_only)})')
    print(f'  ─── revenue_records 合署口徑 ───')
    print(f'     amount (paid - refund)            {fmt(rev_partner_amt):>15}')
    print(f'     firm_amount (事務所實收)           {fmt(rev_partner_firm):>15}   差Excel {fmt(rev_partner_firm - ex_partner_rev)}')
    print(f'  其他收入                   {fmt(ex_other_rev):>15}')
    print(f'  法律010 收入               {fmt(ex_fa0_rev):>15}   毛 ×0.35: {fmt(dash_fa0_share):>10}   毛: {fmt(dash_fa0_gross)}')
    print(f'  支出總計                   {fmt(ex_expense):>15}   {fmt(dash_cost):>15}   {fmt(ex_expense - dash_cost)}')
    print()
    print(f'  Excel 合併利潤             {fmt(ex_profit_merged):>15}')
    print(f'  儀表板「數字 A」           ─                   {fmt(dash_profit):>15}')
    print(f'  差異                                                              {fmt(dash_profit - ex_profit_merged)}')


if __name__ == '__main__':
    main()
