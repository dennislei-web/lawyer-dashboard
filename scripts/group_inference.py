"""
group_name 推算共用模組

CRM 端 case.group 偶爾為空（自 2025-06 起約 18-20% 案件如此）。
此模組根據 assigned_lawyers / office 推算 group_name，供：
  - backfill_group_name.py（歷史回補）
  - scrape_reconciliation.py（爬蟲 ingest 時即時補）
共用。

API：
  load_history(supabase_url, key)  →  GroupHistory 物件
  history.infer(record_date, assigned_lawyers, office) → (group_name, source) 或 (None, 'no_match')
"""
import re
from collections import defaultdict, Counter
from datetime import datetime

# 所別 fallback 預設組（最後一道防線；只在律師完全無前科時使用）
OFFICE_DEFAULT = {
    "新竹所": "竹所一部",
    "桃園所": "桃所一部",
    "高雄所": "雄所一部",
    "台南所": "南所一部",
    "台中所": "中所一部",
    "台北所": "北所一部",
}


def _split_lawyers(s):
    if not s: return []
    return [x.strip() for x in re.split(r"[,，、]\s*", s) if x.strip()]


def _ymonth(date_str):
    return (date_str or "")[:7]


def _year(date_str):
    return (date_str or "")[:4]


class GroupHistory:
    """律師 → 群組歷史。以 (office, year) 分桶，避免跨所污染（如雷皓明北所案件灌爆中所推算）。"""

    def __init__(self):
        # lawyer → office → year → Counter(group_name)
        self.by_office_year = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
        # lawyer → office → Counter(group_name)（同所跨年）
        self.by_office = defaultdict(lambda: defaultdict(Counter))
        # lawyer → year → Counter(group_name)（跨所同年，低信心）
        self.by_year = defaultdict(lambda: defaultdict(Counter))
        # lawyer → Counter(group_name)（全期跨所，最低信心）
        self.all_time = defaultdict(Counter)
        self._lawyers = set()

    def add(self, lawyer, date_str, group_name, office=None):
        if not (lawyer and group_name): return
        y = _year(date_str)
        self._lawyers.add(lawyer)
        if office and y:
            self.by_office_year[lawyer][office][y][group_name] += 1
        if office:
            self.by_office[lawyer][office][group_name] += 1
        if y:
            self.by_year[lawyer][y][group_name] += 1
        self.all_time[lawyer][group_name] += 1

    @property
    def all_lawyers(self):
        return self._lawyers

    def infer(self, record_date, assigned_lawyers, office):
        """回傳 (group_name, source)。會加 mode confidence threshold 避免被法務助理/跨所支援人員污染。

        信心 tier：
          lawyer_year_office  律師同所同年（mode_share ≥ 60% 且 n ≥ 3）
          lawyer_office       律師同所跨年（mode_share ≥ 60%）
          lawyer_strong       任一律師同所眾數 share ≥ 50%
          office_default      上述全失敗 → 用所別預設 group
        """
        MIN_SHARE_STRONG = 0.60
        MIN_SHARE_WEAK = 0.50
        MIN_COUNT_STRONG = 3
        lawyers = _split_lawyers(assigned_lawyers)
        ty = _year(record_date)

        def _check(counter, min_share, min_n):
            if not counter: return None
            top, count = counter.most_common(1)[0]
            total = sum(counter.values())
            if total >= min_n and count / total >= min_share:
                return top
            return None

        # Tier 1：接案律師（第一位）+ 同所同年
        if lawyers and office and ty:
            g = _check(self.by_office_year[lawyers[0]][office].get(ty), MIN_SHARE_STRONG, MIN_COUNT_STRONG)
            if g: return g, "lawyer_year_office"

        # Tier 2：接案律師 + 同所跨年
        if lawyers and office:
            g = _check(self.by_office[lawyers[0]].get(office), MIN_SHARE_STRONG, MIN_COUNT_STRONG)
            if g: return g, "lawyer_office"

        # Tier 3：所有 assigned_lawyers 任一位 + 同所跨年（信心 50%）
        for lawyer in lawyers:
            if office:
                g = _check(self.by_office[lawyer].get(office), MIN_SHARE_WEAK, 2)
                if g: return g, "lawyer_strong"

        # Tier 4：office 預設
        if office and office in OFFICE_DEFAULT:
            return OFFICE_DEFAULT[office], "office_default"
        return None, "no_match"


def load_history(supabase_url, service_key, verify=False, since_date="2024-01-01"):
    """從 revenue_records 撈出所有非空 group_name 的歷史，建立 lawyer→group 索引。"""
    import httpx
    H = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    history = GroupHistory()
    off, page = 0, 1000
    while True:
        r = httpx.get(
            f"{supabase_url}/rest/v1/revenue_records",
            params={
                "select": "record_date,assigned_lawyers,group_name,office",
                "group_name": "not.is.null",
                "record_date": f"gte.{since_date}",
                "is_void": "eq.false",
                "limit": str(page),
                "offset": str(off),
            },
            headers=H, timeout=120, verify=verify,
        )
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            for lawyer in _split_lawyers(row.get("assigned_lawyers")):
                history.add(lawyer, row.get("record_date"), row.get("group_name"), row.get("office"))
        if len(rows) < page: break
        off += page
    return history
