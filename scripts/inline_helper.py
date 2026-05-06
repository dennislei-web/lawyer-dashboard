"""
Inline 分析 helper：
1. dump <name> <start_idx> <count>     -> 印出該批次案件的 prompt context（精簡）
2. save <name> <case_id> <analysis_json_path> -> 寫入 _llm.json + DB
3. progress <name>                     -> 顯示進度
"""
import os, io, sys, json, httpx
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
SCRIPT_DIR = Path(__file__).parent.resolve()
load_dotenv(SCRIPT_DIR / '.env', override=True)

URL = os.environ['SUPABASE_URL']
KEY = os.environ['SUPABASE_SERVICE_KEY']
HDR = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}

DATA_DIR = SCRIPT_DIR / 'briefs' / 'raw_data'


def load_prep(name):
    p = DATA_DIR / f'{name}_prep.json'
    return json.load(open(p, encoding='utf-8'))


def load_llm(name):
    p = DATA_DIR / f'{name}_llm.json'
    if p.exists():
        return json.load(open(p, encoding='utf-8'))
    return []


def save_llm(name, data):
    p = DATA_DIR / f'{name}_llm.json'
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def cmd_dump(name, start, count):
    prep = load_prep(name)
    cases = prep['cases_with_meeting_record']
    end = min(start + count, len(cases))
    for i in range(start, end):
        c = cases[i]
        mr = (c.get('meeting_record') or '')[:2800]
        ts = (c.get('transcript') or '')[:2000]
        print(f'=== CASE {i} ===')
        print(f'id: {c["id"]}')
        print(f'date: {c["case_date"]}')
        print(f'client: {c.get("client_name") or "?"}')
        print(f'case_type: {c.get("case_type") or "?"}')
        print(f'is_signed: {c["is_signed"]}')
        print(f'collected: {c.get("collected") or 0}')
        print(f'lawyer_notes: {c.get("lawyer_notes") or "(無)"}')
        print('--- meeting_record ---')
        print(mr)
        print('--- transcript ---')
        print(ts if ts else '(無)')
        print()


def cmd_save(name, batch_json_path):
    """從 batch_json_path 讀 [{'case_id':..,'analysis':{...}}, ...]，
    寫進 _llm.json 並 patch DB"""
    batch = json.loads(Path(batch_json_path).read_text(encoding='utf-8'))
    prep = load_prep(name)
    case_index = {c['id']: c for c in prep['cases_with_meeting_record']}

    existing = load_llm(name)
    by_id = {x['case_id']: x for x in existing}

    for item in batch:
        cid = item['case_id']
        analysis = item['analysis']
        c = case_index.get(cid)
        if not c:
            print(f'[skip] case_id {cid} 不在 prep.json')
            continue
        rec = {
            'case_id': cid,
            'case_date': c['case_date'],
            'case_type': c.get('case_type'),
            'is_signed': c['is_signed'],
            'collected': c.get('collected') or 0,
            'analysis': analysis,
        }
        by_id[cid] = rec
        # PATCH DB
        r = httpx.patch(
            f'{URL}/rest/v1/consultation_cases',
            params={'id': f'eq.{cid}'},
            headers=HDR,
            json={
                'llm_analysis': analysis,
                'llm_analyzed_at': datetime.utcnow().isoformat() + 'Z',
            },
            timeout=30,
        )
        if r.status_code >= 400:
            print(f'[error] patch DB failed for {cid}: {r.status_code} {r.text[:200]}')
        else:
            print(f'[ok] saved {cid} · {c["case_date"]} · {c.get("client_name") or "?"}')

    save_llm(name, list(by_id.values()))
    print(f'總計已分析: {len(by_id)} / {len(prep["cases_with_meeting_record"])}')


def cmd_progress(name):
    prep = load_prep(name)
    total = len(prep['cases_with_meeting_record'])
    done = load_llm(name)
    print(f'{name}: 已分析 {len(done)} / {total}')
    done_ids = {x['case_id'] for x in done}
    pending = [c for c in prep['cases_with_meeting_record'] if c['id'] not in done_ids]
    print(f'剩餘 {len(pending)} 筆')
    for i, c in enumerate(pending[:5]):
        print(f'  next #{i}: {c["case_date"]} · {c.get("client_name") or "?"} · 簽={c["is_signed"]}')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'dump':
        cmd_dump(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    elif cmd == 'save':
        cmd_save(sys.argv[2], sys.argv[3])
    elif cmd == 'progress':
        cmd_progress(sys.argv[2])
    else:
        print('usage: dump <name> <start> <count> | save <name> <batch.json> | progress <name>')
