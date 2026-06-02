"""里民 LINE OA 好友數 → Supabase

OA：法律010🌸里民專屬法律諮詢 (Channel ID 2009969674)
來源：LINE Messaging API  GET /v2/bot/insight/followers?date=YYYYMMDD
寫入：bd_li_oa_followers(date, followers, targeted_reaches, blocks, source='line_api')

- insight/followers 有 1~3 天延遲，且當日資料可能 status=unready，
  故往回試最近幾天，取第一個 status=ready。
- 沒有 LINE_LIMIN_OA_TOKEN 時直接跳過(exit 0)，不影響其他同步。
- 診斷只印 shape / 狀態，絕不印 token 值。

Usage:  python sync_li_oa_followers.py
"""
from __future__ import annotations
import os, sys, json, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone, date as date_cls
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TOKEN = os.environ.get("LINE_LIMIN_OA_TOKEN", "").strip()
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TABLE = "bd_li_oa_followers"

if not TOKEN:
    print("LINE_LIMIN_OA_TOKEN 未設定 → 跳過好友數同步(不影響其他同步)")
    sys.exit(0)


def get_insight(date_yyyymmdd):
    """回傳 parsed json；遇 429(速率限制)自動退避重試。只印狀態碼，不印 body。"""
    url = "https://api.line.me/v2/bot/insight/followers?" + urllib.parse.urlencode({"date": date_yyyymmdd})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  insight {date_yyyymmdd}: HTTP 429，{wait}s 後重試({attempt+1}/5)", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  insight {date_yyyymmdd}: HTTP {e.code}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  insight {date_yyyymmdd}: {type(e).__name__}", file=sys.stderr)
            return None
    print(f"  insight {date_yyyymmdd}: 連續 429，放棄", file=sys.stderr)
    return None


def supa_upsert(rows):
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?on_conflict=date"
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()


def _row(d, res):
    return {
        "date": d.isoformat(),
        "followers": int(res.get("followers") or 0),
        "targeted_reaches": res.get("targetedReaches"),
        "blocks": res.get("blocks"),
        "source": "line_api",
    }


BACKFILL = int(os.environ.get("BACKFILL_DAYS", "0") or 0)


def db_min_date():
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?select=date&order=date.asc&limit=1"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Accept": "application/json"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return date_cls.fromisoformat(data[0]["date"]) if data else None
    except Exception:
        return None


def extend_history(max_fill=4):
    """從目前最早日往前，溫和補幾天(配額友善)。碰到 unready=已達 LINE 保留邊界就停。"""
    mn = db_min_date()
    if not mn:
        return
    filled = 0
    for i in range(1, 15):
        d = mn - timedelta(days=i)
        res = get_insight(d.strftime("%Y%m%d"))
        if res and res.get("status") == "ready" and res.get("followers") is not None:
            supa_upsert([_row(d, res)]); filled += 1
            print(f"  往前補 {d.isoformat()} = {res.get('followers')}")
        elif res is not None:
            print(f"  {d.isoformat()} status={res.get('status')} → 已達 LINE 保留邊界，停止往前")
            break
        else:
            break  # 429/錯誤 → 留待下次
        if filled >= max_fill:
            break
        time.sleep(1.5)
    if filled:
        print(f"✓ 本次往前延伸 {filled} 天")


def main():
    now_tpe = datetime.now(timezone.utc) + timedelta(hours=8)

    if BACKFILL > 0:
        # 回填過去 N 天；節流避免 429。統計 ready / 非 ready(unready=超出 LINE 保留期)
        rows, n_ready, n_unready = [], 0, 0
        for back in range(1, BACKFILL + 1):
            d = (now_tpe - timedelta(days=back)).date()
            res = get_insight(d.strftime("%Y%m%d"))
            if res and res.get("status") == "ready" and res.get("followers") is not None:
                rows.append(_row(d, res)); n_ready += 1
            elif res is not None:
                n_unready += 1  # status=unready/out_of_service → LINE 已無此日資料
            time.sleep(0.35)  # 節流
        supa_upsert(rows)
        if rows:
            lo, hi = rows[-1]["date"], rows[0]["date"]
            print(f"✓ 回填 {n_ready} 天({lo} → {hi})；另有 {n_unready} 天 LINE 已無資料(保留期外)")
        else:
            print(f"⚠ 區間內無 ready 資料(unready {n_unready} 天)", file=sys.stderr)
        return

    # 日常：往回找最近一個 ready 的日期(最多回溯 5 天)
    wrote = False
    for back in range(1, 6):
        d = (now_tpe - timedelta(days=back)).date()
        res = get_insight(d.strftime("%Y%m%d"))
        if not res:
            continue
        status = res.get("status")
        print(f"  {d.isoformat()}: status={status} followers={res.get('followers')}")
        if status == "ready":
            supa_upsert([_row(d, res)])
            print(f"✓ {d.isoformat()} 好友數 {res.get('followers')} 已寫入")
            wrote = True
            break
    if not wrote:
        print("⚠ 最近 5 天都沒有 ready 的 insight 資料，本次未寫入", file=sys.stderr)
    # 每天溫和往前延伸歷史(配額友善)，直到碰到 LINE 保留邊界
    extend_history(max_fill=4)


if __name__ == "__main__":
    main()
