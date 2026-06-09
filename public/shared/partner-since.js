// AUTO-GENERATED from scripts/partners/partner_roster.json — 勿手改。
// 改名冊後跑 python scripts/partners/build_partner_since_js.py 重新產生。
// 提供 window.PARTNER_SINCE 與 window.isPartnerRecord(r)：時間感知合署判斷，
// 收款日早於該合署 group「最早轉合署成員」生效日 → 非合署（轉前帶走案的委任費歸所內）。
(function () {
  var PARTNER_SINCE = {
    "孫少輔": "2023-11-01",
    "許致維": "2024-04-01",
    "劉明潔": "2025-07-01",
    "方心瑜": "2025-10-01",
    "陳璽仲": "2024-09-01",
    "許煜婕": "2024-11-01",
    "蕭予馨": "2025-01-01",
    "徐棠娜": "2025-02-01",
    "林昀": "2025-03-01",
    "李昭萱": "2025-06-01",
    "柯雪莉": "2025-09-01",
    "吳柏慶": "2026-03-01",
    "蘇萱": "2026-05-01",
    "李家泓": "2026-06-01",
    "黃顯皓": "2025-10-01",
    "黃世欣": "2020-01-01",
    "劉誠夫": "2023-11-01",
    "陳俊瑋": "2023-11-01",
    "曾秉浩": "2023-11-01"
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
