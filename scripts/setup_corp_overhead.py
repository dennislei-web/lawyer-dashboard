#!/usr/bin/env python3
"""補登「公司 entity 共通成本」科目與 115 年 finance_data。

idempotent：可重複執行。如果 category 或 finance_data 已存在會跳過。
適用情境：
  1. 首次補登
  2. 「清除全年資料」按鈕誤觸後重灌
  3. 切換到新年度需要 seed 預算

執行：
  python3 scripts/setup_corp_overhead.py
  python3 scripts/setup_corp_overhead.py --year 116   # 預設 115
"""
import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/projects/lawyer-dashboard/scripts/.env'))
SK = os.environ.get('SUPABASE_SERVICE_KEY')
if not SK:
    print('ERROR: SUPABASE_SERVICE_KEY missing', file=sys.stderr); sys.exit(1)
H = {'apikey': SK, 'Authorization': f'Bearer {SK}',
     'Content-Type':'application/json', 'Prefer':'return=representation'}
BASE = 'https://zpbkeyhxyykbvownrngf.supabase.co/rest/v1'

CATEGORY = {
    'code': 'corp_overhead',
    'name': '公司 entity 共通成本',
    'section': 'operating_expense',
    'sort_order': 36,
    'is_subtotal': False,
}

# 115 年資料 (來自 Excel「115年公司、事務所利潤明細」)
DATA_115 = {
    'actual':  {1: 67088, 2: 66845, 3: 2394},  # 後續月份隨 Excel 更新後補
    'budget':  {1: 67088, 2: 66845, 3: 2394,
                4: 1442, 5: 1442, 6: 1442, 7: 1442, 8: 1442, 9: 1442,
                10: 1442, 11: 1442, 12: 1442},
}
NOTES = {
    1: '系統訂閱費(年付) 65,646 + 折舊 1,442',
    2: '系統訂閱費(年付) 65,403 + 折舊 1,442',
    3: '折舊 1,442 + 營業稅 952',
}


def ensure_category():
    r = requests.get(f'{BASE}/finance_categories', headers=H,
                     params={'select':'id,code', 'code':f'eq.{CATEGORY["code"]}'}, timeout=30)
    r.raise_for_status()
    existing = r.json()
    if existing:
        print(f'✓ Category {CATEGORY["code"]} 已存在 id={existing[0]["id"]}')
        return existing[0]['id']
    r2 = requests.post(f'{BASE}/finance_categories', headers=H, json=CATEGORY, timeout=30)
    r2.raise_for_status()
    new_id = r2.json()[0]['id']
    print(f'+ Category {CATEGORY["code"]} 已新增 id={new_id}')
    return new_id


def ensure_data(year, cat_id, data_dict):
    # 查現有
    r = requests.get(f'{BASE}/finance_data', headers=H, params={
        'select':'month,data_type,amount', 'category_id': f'eq.{cat_id}',
        'fiscal_year': f'eq.{year}',
    }, timeout=30)
    r.raise_for_status()
    existing = {(x['month'], x['data_type']): x['amount'] for x in r.json()}

    rows = []
    for dt, monthly in data_dict.items():
        for m, amt in monthly.items():
            key = (m, dt)
            if key in existing:
                if existing[key] == amt:
                    continue  # 完全一致跳過
                # 不一致：略過，避免覆蓋人為調整
                print(f'  ~ {year}-{m:02d} {dt}: 已存在 {existing[key]} ≠ 目標 {amt}，跳過')
                continue
            rows.append({
                'category_id': cat_id, 'fiscal_year': year, 'month': m,
                'data_type': dt, 'amount': amt,
                'notes': NOTES.get(m) if dt == 'actual' else
                         (NOTES.get(m) or '折舊 only（系統訂閱已 1-2 月年付完）' if m >= 4 else None),
            })

    if not rows:
        print(f'  finance_data ({year}): 全部已存在，無需新增')
        return
    r2 = requests.post(f'{BASE}/finance_data', headers=H, json=rows, timeout=60)
    r2.raise_for_status()
    print(f'+ finance_data ({year}): 新增 {len(rows)} 筆')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=115, help='民國年 (預設 115)')
    args = ap.parse_args()

    cat_id = ensure_category()
    if args.year == 115:
        ensure_data(115, cat_id, DATA_115)
    else:
        print(f'(年度 {args.year} 沒有預設資料，僅確保 category 存在)')

    # 驗證
    print('\n─── 驗證 ───')
    r = requests.get(f'{BASE}/finance_data', headers=H, params={
        'select':'month,data_type,amount', 'category_id': f'eq.{cat_id}',
        'fiscal_year': f'eq.{args.year}', 'order':'data_type,month',
    }, timeout=30).json()
    if not r:
        print('(無 finance_data)')
        return
    act = sum(x['amount'] for x in r if x['data_type']=='actual')
    bud = sum(x['amount'] for x in r if x['data_type']=='budget')
    print(f'{args.year} 年 actual: {act:,} ({act/10000:.1f} 萬)')
    print(f'{args.year} 年 budget: {bud:,} ({bud/10000:.1f} 萬)')


if __name__ == '__main__':
    main()
