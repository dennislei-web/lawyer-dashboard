#!/usr/bin/env python3
"""
build_partner_since_js.py — 從 partner_roster.json 產生 public/shared/partner-since.js。
讓前端各頁（OKR 等）共用「時間感知合署判斷」，不必各自寫死 PARTNER_SINCE（避免 drift）。
  python scripts/partners/build_partner_since_js.py
"""
import json, os, io, sys
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
roster = json.load(open(os.path.join(ROOT, "scripts/partners/partner_roster.json"), encoding="utf-8"))["lawyers"]
since = {l["name"]: l["since"] for l in roster}
entries = ",\n".join(f"    {json.dumps(n, ensure_ascii=False)}: {json.dumps(d)}" for n, d in since.items())
js = """// AUTO-GENERATED from scripts/partners/partner_roster.json — 勿手改。
// 改名冊後跑 python scripts/partners/build_partner_since_js.py 重新產生。
// 提供 window.PARTNER_SINCE 與 window.isPartnerRecord(r)：時間感知合署判斷，
// 收款日早於該合署 group「最早轉合署成員」生效日 → 非合署（轉前帶走案的委任費歸所內）。
(function () {
  var PARTNER_SINCE = {
%s
  };
  var _d = {}; Object.keys(PARTNER_SINCE).forEach(function (n) { _d[n] = new Date(PARTNER_SINCE[n]); });
  var _names = Object.keys(PARTNER_SINCE);
  var _cache = {};
  function _groupSince(g) {
    if (_cache.hasOwnProperty(g)) return _cache[g];
    var ms = null;
    for (var i = 0; i < _names.length; i++) {
      if (g.indexOf(_names[i]) !== -1) { var s = _d[_names[i]]; if (s && (ms === null || s < ms)) ms = s; }
    }
    _cache[g] = ms; return ms;
  }
  function isPartnerRecord(r) {
    if (!r.group_name || r.group_name.indexOf('合署') === -1) return false;
    var s = _groupSince(r.group_name);
    if (!s || !r.record_date) return true;
    return new Date(r.record_date) >= s;
  }
  window.PARTNER_SINCE = PARTNER_SINCE;
  window.isPartnerRecord = isPartnerRecord;
})();
""" % entries
out = os.path.join(ROOT, "public/shared/partner-since.js")
open(out, "w", encoding="utf-8", newline="\n").write(js)
print(f"wrote {out} ({len(since)} 位)")
