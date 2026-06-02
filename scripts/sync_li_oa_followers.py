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
import os, sys, json
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
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
    url = "https://api.line.me/v2/bot/insight/followers?" + urllib.parse.urlencode({"date": date_yyyymmdd})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # 只印狀態碼 + 錯誤 type，不印 body 細節(避免任何外洩)
        print(f"  insight {date_yyyymmdd}: HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  insight {date_yyyymmdd}: {type(e).__name__}", file=sys.stderr)
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


def main():
    now_tpe = datetime.now(timezone.utc) + timedelta(hours=8)

    if BACKFILL > 0:
        # 回填過去 N 天所有 ready 的 insight(insight 資料有起始日，太舊會 unready/no-data)
        rows = []
        for back in range(1, BACKFILL + 1):
            d = (now_tpe - timedelta(days=back)).date()
            res = get_insight(d.strftime("%Y%m%d"))
            if res and res.get("status") == "ready" and res.get("followers") is not None:
                rows.append(_row(d, res))
        supa_upsert(rows)
        if rows:
            lo, hi = rows[-1]["date"], rows[0]["date"]
            print(f"✓ 回填 {len(rows)} 天({lo} → {hi})")
        else:
            print("⚠ 回填區間內沒有 ready 資料", file=sys.stderr)
        return

    # 日常：往回找最近一個 ready 的日期(最多回溯 5 天)
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
            return
    print("⚠ 最近 5 天都沒有 ready 的 insight 資料，本次未寫入", file=sys.stderr)


if __name__ == "__main__":
    main()
