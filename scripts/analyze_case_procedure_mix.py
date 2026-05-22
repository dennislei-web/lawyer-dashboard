"""
按律師 × 年度，分析諮詢案中「委任完整訴訟程序」vs「委任部分程序」的佔比。

分類規則（A 優先，A∪B 互斥）：
- A 完整訴訟程序：進法院走程序 (民/家/刑各審 + 強制執行 + 保護令 + 調解程序 + 抗告 + 包套...)
- B 部分程序：律師函、各類協議書、代協商、撰寫書狀、支付命令、本票裁定、證人、法律顧問、契約...
- 案由 / 加值 / 通道 tag (離婚、子女親權、加急、現場諮詢...) 不影響分類
- 一案同時有 A 和 B → 算 A
- 一案 is_signed=False → 算「未成案」（不算 A/B）
"""
from __future__ import annotations
import os
import sys
import requests
import pandas as pd
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
SUPA_URL = os.environ['SUPABASE_URL']
SUPA_KEY = os.environ['SUPABASE_SERVICE_KEY']
HEADERS = {'apikey': SUPA_KEY, 'Authorization': f'Bearer {SUPA_KEY}'}

A_TAGS = {
    # 民事
    '民事一審', '民事二審', '民事三審',
    # 家事
    '家事一審', '家事二審', '家事三審',
    # 刑事
    '刑事偵查程序', '刑事一審程序', '刑事二審程序', '刑事三審程序',
    '刑事告訴', '刑事再議程序',
    '刑事附帶民事一審程序', '刑事一審附帶民事',
    # 執行 / 救濟
    '強制執行', '強制執行(五年)',
    '抗告', '暫時保護令抗告',
    '通常保護令程序', '暫時處分',
    # 調解
    '家事調解程序', '勞動爭議調解',
    # 其他法院程序
    '改定監護', '收養程序', '確認親子關係',
    '假扣押聲請', '聲請核發債權憑證', '聲請限定繼承程序',
    '履行同居', '法院分別財產制登記',
    # 套裝
    '包套',
}
B_TAGS = {
    # 文書
    '律師函', '存證信函',
    # 協議書
    '離婚協議書', '婚姻中協議', '和解協議書', '還款協議書',
    '撰寫和解書', '協議書撰寫',
    # 協商 / 調解
    '代協商', '律師協商', '陪同調解', '調解聲請狀',
    # 撰狀
    '撰寫書狀', '民事起訴狀撰寫',
    # 出庭附屬
    '證人', '警詢', '陪偵', '閱卷',
    # 法律文件
    '公證費', '代筆遺囑',
    # 速件程序
    '支付命令', '本票裁定',
    # 顧問 / 契約
    '法律顧問', '常年企業法律顧問', '契約',
    # 律見 (羈押所探視)
    '律見',
    # 其他偏 partial
    '請求履行協議',
}

CHANNEL_TAGS = {'現場諮詢', '視訊諮詢', '電話諮詢'}
# 案由 / 加值 — 不影響 A/B 分類（檢驗用）
SUBJECT_TAGS = {
    '離婚', '子女親權', '會面交往', '酌定探視', '剩餘財產分配',
    '給付扶養費', '返還代墊扶養費', '侵害配偶權', '損害賠償',
    '過失傷害', '詐欺', '不當得利', '侵權行為', '拋棄繼承',
    '律師指定費', '加急', '其他',
}


def fetch_all(table: str, select: str, page: int = 1000):
    rows = []
    off = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/{table}',
            params={'select': select, 'limit': page, 'offset': off},
            headers=HEADERS,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows.extend(data)
        if len(data) < page:
            break
        off += page
    return rows


def classify(case_type: str, is_signed: bool) -> str:
    """回傳分類：A_full / B_partial / signed_other / unsigned"""
    if not is_signed:
        return 'unsigned'
    tags = [t.strip() for t in (case_type or '').split(',') if t.strip()]
    has_a = any(t in A_TAGS for t in tags)
    has_b = any(t in B_TAGS for t in tags)
    if has_a:
        return 'A_full'
    if has_b:
        return 'B_partial'
    return 'signed_other'  # 已成案但 tag 只有通道/案由/加值


def main():
    print('讀取 lawyers...', file=sys.stderr)
    lawyers = {l['id']: l for l in fetch_all('lawyers', 'id,name,role,office')}
    print(f'  {len(lawyers)} 位', file=sys.stderr)

    print('讀取 consultation_cases...', file=sys.stderr)
    cases = fetch_all('consultation_cases',
                      'lawyer_id,case_date,case_type,is_signed')
    print(f'  {len(cases)} 件', file=sys.stderr)

    df = pd.DataFrame(cases)
    df['year'] = pd.to_datetime(df['case_date']).dt.year
    df['bucket'] = df.apply(
        lambda r: classify(r['case_type'], bool(r['is_signed'])), axis=1
    )
    df['lawyer_name'] = df['lawyer_id'].map(
        lambda x: (lawyers.get(x) or {}).get('name') or '?'
    )
    df['lawyer_role'] = df['lawyer_id'].map(
        lambda x: (lawyers.get(x) or {}).get('role') or '?'
    )
    # 過濾 legal_staff（與資料健康度頁一致）
    df = df[df['lawyer_role'] != 'legal_staff']

    # ===== 1) 全所總覽 =====
    print()
    print('=' * 96)
    print('全所總覽（各年度）')
    print('=' * 96)
    overall_rows = []
    for y, sub in df.groupby('year'):
        total = len(sub)
        a = (sub['bucket'] == 'A_full').sum()
        b = (sub['bucket'] == 'B_partial').sum()
        other = (sub['bucket'] == 'signed_other').sum()
        unsigned = (sub['bucket'] == 'unsigned').sum()
        signed = a + b + other
        overall_rows.append({
            '年度': int(y),
            '總諮詢': total,
            '已成案': signed,
            '成案率%': round(signed / total * 100, 1) if total else 0,
            '完整訴訟A': a,
            'A/全諮詢%': round(a / total * 100, 1) if total else 0,
            'A/已成案%': round(a / signed * 100, 1) if signed else 0,
            '部分程序B': b,
            'B/全諮詢%': round(b / total * 100, 1) if total else 0,
            'B/已成案%': round(b / signed * 100, 1) if signed else 0,
            '已成案未分類': other,
        })
    overall = pd.DataFrame(overall_rows).sort_values('年度')
    print(overall.to_string(index=False))

    # ===== 2) 每律師 × 年度 =====
    print()
    print('=' * 96)
    print('每律師 × 年度（按律師字母排序，年度遞增）')
    print('=' * 96)
    grp = df.groupby(['lawyer_name', 'year'])
    rows = []
    for (name, y), sub in grp:
        total = len(sub)
        if total < 5:  # 少於 5 件視為樣本太小忽略
            continue
        a = (sub['bucket'] == 'A_full').sum()
        b = (sub['bucket'] == 'B_partial').sum()
        other = (sub['bucket'] == 'signed_other').sum()
        signed = a + b + other
        rows.append({
            '律師': name,
            '年度': int(y),
            '總諮詢': total,
            '成案': signed,
            '成%': round(signed / total * 100, 1) if total else 0,
            'A': a,
            'A/全%': round(a / total * 100, 1) if total else 0,
            'A/成%': round(a / signed * 100, 1) if signed else 0,
            'B': b,
            'B/全%': round(b / total * 100, 1) if total else 0,
            'B/成%': round(b / signed * 100, 1) if signed else 0,
        })
    detail = pd.DataFrame(rows).sort_values(['律師', '年度'])
    # 用 to_string 整齊輸出
    with pd.option_context('display.max_rows', None,
                           'display.max_columns', None,
                           'display.width', 200):
        print(detail.to_string(index=False))

    # ===== 3) 最近年度（2026）排行：A 比例 與 B 比例 top10 =====
    latest = int(df['year'].max())
    print()
    print('=' * 96)
    print(f'{latest} 年律師排行（總諮詢 ≥ 30）')
    print('=' * 96)
    cur = detail[(detail['年度'] == latest) & (detail['總諮詢'] >= 30)]
    print('\n— A 完整訴訟佔總諮詢比 Top 10 —')
    print(cur.sort_values('A/全%', ascending=False).head(10).to_string(index=False))
    print('\n— B 部分程序佔總諮詢比 Top 10 —')
    print(cur.sort_values('B/全%', ascending=False).head(10).to_string(index=False))

    # ===== 4) sanity: 未分類 tag 抽樣 =====
    print()
    print('=' * 96)
    print('健檢：已成案但 case_type 完全沒有 A/B tag 的樣本（隨機 8 件）')
    print('=' * 96)
    so = df[df['bucket'] == 'signed_other'].copy()
    if not so.empty:
        sample = so.sample(min(8, len(so)), random_state=42)[
            ['lawyer_name', 'case_date', 'case_type']
        ]
        print(sample.to_string(index=False))
        # 並印 tag 出現頻率
        tag_cnt = defaultdict(int)
        for ct in so['case_type'].dropna():
            for t in ct.split(','):
                t = t.strip()
                if t and t not in CHANNEL_TAGS:
                    tag_cnt[t] += 1
        if tag_cnt:
            print('\nsigned_other case_type tag 頻次（去除諮詢通道）:')
            for t, c in sorted(tag_cnt.items(), key=lambda x: -x[1])[:15]:
                in_subj = ' [案由]' if t in SUBJECT_TAGS else ''
                print(f'  {c:4}  {t}{in_subj}')


if __name__ == '__main__':
    main()
