"""
資深律師轉合署 案件明細 Excel → 乾淨 CSV
-----------------------------------------
輸入：drive-download-...-3-001 底下所有 "NNN年XX律師案件明細.xlsx"
  7 位律師：李昭萱、林昀、徐棠娜、許煜婕、陳璽仲、蕭予馨、吳柏慶

輸出：
  - senior_profit_share.csv   每律師每月分潤明細（含 tier / ratio / 當事人）
  - senior_cases.csv          每律師每月案件逐筆（同 cases.csv schema）
  - senior_monthly_totals.csv 每律師每月 喆律分潤 vs 律師分潤 總計
  - _senior_parse_issues.txt  解析異常

Sheet 結構（每月一張，sheet 名 = YYMM 如 11406）：
  1. 頂部：案件明細（XX律師案件 ... 當事人 / 接案人員 / 金額 / 日期 / ...）
  2. 中段：分潤（XX律師分潤 ... 喆律應付 / XX分潤 / 喆律分潤 / XX應付 ...）
  3. 底部：結算表（XX律師提供 ...）— 不解析，僅作資訊

分潤規則（通用）：
  - 比例 0.7 → 諮詢成案：律師 70% / 喆律 30%
  - 比例 0.6 → 喆律轉案：律師 60% / 喆律 40%
  - 比例 0.1 → 自案：律師 90% / 喆律 10%（右表，ratio = 喆律抽成）
  - 比例 1.0 → 諮詢（100% 律師）
  - 比例 0.05 → 成案獎金（諮詢律師才有）
  - 其他比例 → tier='其他'，保留原值
"""
import openpyxl
from pathlib import Path
import csv, os, re, sys, io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ---------- 設定（可被環境變數覆蓋）----------
_env_input = os.environ.get('PARTNERS_SENIOR_INPUT_DIRS', '').strip()
_env_output = os.environ.get('PARTNERS_OUTPUT_DIR', '').strip()
INPUT_DIRS = [d for d in _env_input.split(os.pathsep) if d] if _env_input else [
    r'C:\Users\admin\Desktop\新增資料夾\drive-download-20260419T022533Z-3-001',
]
SENIOR_LAWYERS = ['李昭萱', '林昀', '徐棠娜', '許煜婕', '陳璽仲', '蕭予馨', '吳柏慶']
FILENAME_PATTERN = re.compile(r'(\d{3})年.*?(' + '|'.join(SENIOR_LAWYERS) + r')律師案件明細')
OUTPUT_DIR = Path(_env_output) if _env_output else Path(r'C:\Users\admin\Desktop\新增資料夾\合署律師分析_output')

def find_input_files():
    results = []
    for d in INPUT_DIRS:
        p = Path(d)
        if not p.exists(): continue
        for f in p.glob('*.xlsx'):
            m = FILENAME_PATTERN.search(f.name)
            if not m: continue
            roc_year = int(m.group(1))
            lawyer = m.group(2)
            results.append((f, roc_year, lawyer))
    return sorted(results, key=lambda x: (x[2], x[1]))

# ---------- sheet 分類 ----------
YYMM_RE = re.compile(r'^(\d{3})(\d{2})$')

def classify_sheet(sn):
    sn = sn.strip()
    if sn == '綜合': return (None, None, 'summary')
    m = YYMM_RE.match(sn)
    if not m: return (None, None, f'unrecognised name: {sn}')
    y, mo = int(m.group(1)), int(m.group(2))
    if not (100 <= y <= 120 and 1 <= mo <= 12):
        return (None, None, f'year/month out of range: {sn}')
    return (y, mo, None)

# ---------- helpers ----------
def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def to_num(x, default=0.0):
    if x is None: return default
    if is_num(x): return float(x)
    try: return float(str(x).replace(',', ''))
    except: return default

SECTION_END_KEYWORDS = ('合計', '結算金額', '折抵', '結餘', '備註', '喆律利潤')

def is_row_blank(row, end=12):
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in row[:end])

# ---------- tier 推論 ----------
def tier_from_ratio(side, ratio, tier_hint=None):
    """side = 'left' (喆律端收款，律師抽成) or 'right' (律師端收款，付給喆律)"""
    if tier_hint:
        if '諮詢成案' in tier_hint: return '諮詢成案'
        if '成案獎金' in tier_hint: return '成案獎金'
        if tier_hint == '諮詢': return '諮詢'
        if '轉案' in tier_hint: return '喆律轉案'
        if '自案' in tier_hint: return '自案'
    if ratio is None:
        return '其他'
    r = round(float(ratio), 3)
    if side == 'left':
        if r == 1.0: return '諮詢'
        if r == 0.7: return '諮詢成案'
        if r == 0.6: return '喆律轉案'
        if r == 0.05: return '成案獎金'
        return '其他'
    else:  # right side — ratio = 喆律抽成
        if r == 0.1: return '自案'
        if r in (0.3, 0.35): return '法律010轉案'  # 0.3 原規則, 0.35 後續調整
        return '其他-自案'

# ---------- 案件明細解析 ----------
CASE_COL_MAP = {
    '當事人': 'client',
    '委任人': 'client',
    '接案人員': 'handlers',
    '金額': 'amount',
    '日期': 'date',
    '備註': 'note',
    '品牌': 'brand',
    '接案所': 'office',
    '部門': 'dept',
    '類型': 'case_type',
    '是否作廢': 'voided',
    '客戶來源': 'source',
}

def find_case_header(rows):
    """Return (header_row_idx, col_map) for the case-details table, or None."""
    for i, row in enumerate(rows):
        if i > 5: break  # header is near top
        vals = row
        if not vals: continue
        first = str(vals[0]) if vals[0] is not None else ''
        if '律師案件' not in first and '案件' not in first:
            continue
        # map cols
        idx = {}
        for j, v in enumerate(vals):
            if v is None: continue
            s = str(v).strip()
            if s in CASE_COL_MAP and CASE_COL_MAP[s] not in idx:
                idx[CASE_COL_MAP[s]] = j
        if 'client' in idx and 'amount' in idx:
            return (i, idx)
    return None

def parse_case_section(rows, lawyer, year, month):
    out = []
    found = find_case_header(rows)
    if not found: return out
    header_idx, idx = found
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        if is_row_blank(row): break
        client = row[idx['client']] if idx['client'] < len(row) else None
        if client is None: continue
        client_s = str(client).strip()
        if not client_s or client_s in ('小計', '合計', '總計', '姓名', '當事人'):
            break
        amt = row[idx['amount']] if 'amount' in idx and idx['amount'] < len(row) else None
        if isinstance(amt, str):
            try: amt = float(amt.replace(',', ''))
            except: pass
        dt = row[idx['date']] if 'date' in idx and idx['date'] < len(row) else None
        date_str = dt.strftime('%Y-%m-%d') if isinstance(dt, datetime) else (str(dt) if dt is not None else None)
        def gv(f):
            j = idx.get(f)
            return row[j] if j is not None and j < len(row) else None
        out.append({
            'lawyer': lawyer, 'year': year, 'month': month,
            'section': '承辦',  # senior 律師大多是承辦/轉案；區分交由分潤判斷
            'client': client_s,
            'handlers': gv('handlers'),
            'amount': amt,
            'date': date_str,
            'note': gv('note'),
            'brand': gv('brand'),
            'office': gv('office'),
            'dept': gv('dept'),
            'case_type': gv('case_type'),
            'voided': gv('voided'),
            'source': gv('source'),
        })
    return out

# ---------- 分潤解析 ----------
def find_profit_header(rows):
    """Return list of (idx, right_col) for each profit-table header found."""
    results = []
    for i, row in enumerate(rows):
        first = str(row[0]).strip() if row[0] is not None else ''
        if '分潤' not in first: continue
        if '喆律應付' not in ' '.join(str(v) for v in row if v is not None): continue
        # find right-table start col (XX應付 != 喆律應付)
        right_col = None
        for j, v in enumerate(row):
            if v is None or j <= 1: continue
            s = str(v).strip()
            if s.endswith('應付') and s != '喆律應付' and '-' not in s:
                right_col = j
                break
        results.append((i, right_col))
    return results

def parse_profit_section(rows, lawyer, year, month):
    """Return list of profit entries."""
    entries = []
    headers = find_profit_header(rows)
    if not headers: return entries

    start_idx, right_col = headers[0]

    # optional: skip over the 姓名/金額/比例 sub-header row(s)
    i = start_idx + 1

    in_other_section = False  # 喆律應付-其他
    while i < len(rows):
        row = rows[i]
        first = str(row[0]).strip() if row[0] is not None else ''

        # stop if hit end keywords at col 0
        if any(k in first for k in SECTION_END_KEYWORDS):
            # if 喆律應付 appears again in col 1 (e.g. summary 喆律應付 xxx), stop
            break

        # check col 1 sub-section markers
        c1 = row[1] if len(row) > 1 else None
        c1s = str(c1).strip() if c1 is not None else ''
        if c1s in ('喆律應付-其他', '喆律應付 - 其他'):
            in_other_section = True
            i += 1
            continue
        if c1s in ('姓名', '小計', '合計'):
            # 小計 = left table ended; check right too
            if c1s == '小計':
                # see if right-table data still follows — usually right 小計 might appear later
                pass
            i += 1
            continue
        if c1s in ('喆律應付', '喆律利潤'):
            # summary row
            i += 1
            continue

        # extract left-table cells
        c2 = row[2] if len(row) > 2 else None
        c3 = row[3] if len(row) > 3 else None
        c4 = row[4] if len(row) > 4 else None
        c5 = row[5] if len(row) > 5 else None

        # In 喆律應付-其他 sub-section, col 5 holds tier text (諮詢 / 成案獎金)
        left_tier_hint = None
        if in_other_section and isinstance(c5, str) and c5.strip() in ('諮詢', '成案獎金'):
            left_tier_hint = c5.strip()

        # left-table data row: c1=client, c2=amount, c3=ratio
        #   ratio must be in (0, 1]; reject rows where c3 is some other number
        if (c1s and c1s not in ('姓名',)
                and is_num(c2) and is_num(c3)
                and 0 < float(c3) <= 1):
            amt = to_num(c2)
            ratio = float(c3)
            lawyer_amt = to_num(c4) if is_num(c4) else amt * ratio
            zhelu_amt = to_num(c5) if (is_num(c5) and not in_other_section) else amt - lawyer_amt
            tier = tier_from_ratio('left', ratio, left_tier_hint)
            entries.append({
                'lawyer': lawyer, 'year': year, 'month': month,
                'side': 'zhelu_handled',   # 喆律收款端
                'tier': tier,
                'client': c1s,
                'case_amount': amt,
                'ratio': ratio,
                'lawyer_amt': lawyer_amt,
                'zhelu_amt': zhelu_amt,
                'note': None,
            })

        # right-table data (律師自案，付給喆律)
        if right_col is not None:
            rc1 = row[right_col] if right_col < len(row) else None
            rc2 = row[right_col + 1] if right_col + 1 < len(row) else None
            rc3 = row[right_col + 2] if right_col + 2 < len(row) else None
            rc1s = str(rc1).strip() if rc1 is not None else ''
            if (rc1s and rc1s not in ('姓名', '小計', '合計')
                and is_num(rc2) and is_num(rc3)
                and 0 < float(rc3) <= 1):
                amt = to_num(rc2)
                ratio = float(rc3)  # ratio = 喆律抽成比例
                zhelu_amt = amt * ratio
                lawyer_amt = amt - zhelu_amt
                tier = tier_from_ratio('right', ratio)
                entries.append({
                    'lawyer': lawyer, 'year': year, 'month': month,
                    'side': 'lawyer_handled',  # 律師收款端
                    'tier': tier,
                    'client': rc1s,
                    'case_amount': amt,
                    'ratio': ratio,
                    'lawyer_amt': lawyer_amt,
                    'zhelu_amt': zhelu_amt,
                    'note': None,
                })

        i += 1

    return entries

# ---------- main ----------
def main():
    files = find_input_files()
    print(f'Found {len(files)} senior-lawyer files:')
    for f, y, l in files:
        print(f'  {y} {l}  -  {f.name}')
    print()

    profit_rows = []
    cases_rows = []
    month_totals = []
    issues = []

    for fpath, roc_year, lawyer in files:
        try:
            wb = openpyxl.load_workbook(fpath, data_only=True)
        except Exception as e:
            issues.append(f'CANNOT OPEN {fpath.name}: {e}')
            continue

        for sheet_name in wb.sheetnames:
            year, month, note = classify_sheet(sheet_name)
            if year is None:
                if note and 'summary' not in note:
                    issues.append(f'{fpath.name} :: {sheet_name}  -  skipped ({note})')
                continue
            if year != roc_year:
                # tolerate — some files bundle 114 and 115 data
                pass

            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))

            # cases
            try:
                cases = parse_case_section(rows, lawyer, year, month)
                cases_rows.extend(cases)
            except Exception as e:
                issues.append(f'{fpath.name} :: {sheet_name}  case-parse failed: {e}')

            # profit
            try:
                entries = parse_profit_section(rows, lawyer, year, month)
                profit_rows.extend(entries)
                # monthly total from entries
                z = sum(e['zhelu_amt'] for e in entries)
                l = sum(e['lawyer_amt'] for e in entries)
                if entries:
                    month_totals.append({
                        'lawyer': lawyer, 'year': year, 'month': month,
                        'zhelu_total': z, 'lawyer_total': l,
                    })
            except Exception as e:
                issues.append(f'{fpath.name} :: {sheet_name}  profit-parse failed: {e}')

        wb.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # senior_profit_share.csv
    with open(OUTPUT_DIR / 'senior_profit_share.csv', 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=[
            'lawyer', 'year', 'month', 'side', 'tier', 'client',
            'case_amount', 'ratio', 'lawyer_amt', 'zhelu_amt', 'note',
        ])
        w.writeheader()
        for r in profit_rows: w.writerow(r)

    # senior_cases.csv — same schema as cases.csv
    with open(OUTPUT_DIR / 'senior_cases.csv', 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=[
            'lawyer', 'year', 'month', 'section',
            'client', 'handlers', 'amount', 'date', 'note', 'brand',
            'office', 'dept', 'case_type', 'voided', 'source',
        ])
        w.writeheader()
        for r in cases_rows: w.writerow(r)

    # senior_monthly_totals.csv
    with open(OUTPUT_DIR / 'senior_monthly_totals.csv', 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=['lawyer', 'year', 'month', 'zhelu_total', 'lawyer_total'])
        w.writeheader()
        for r in month_totals: w.writerow(r)

    # issues
    with open(OUTPUT_DIR / '_senior_parse_issues.txt', 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(issues) if issues else 'no issues')

    print(f'\nwrote {len(profit_rows)} profit entries')
    print(f'wrote {len(cases_rows)} case rows')
    print(f'wrote {len(month_totals)} monthly totals')
    print(f'issues: {len(issues)}')
    print(f'\noutput -> {OUTPUT_DIR}')

if __name__ == '__main__':
    main()
