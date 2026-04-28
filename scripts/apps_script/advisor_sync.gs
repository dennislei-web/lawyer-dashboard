/**
 * 法律顧問儀表板 - Google Sheet → Supabase 同步
 * 每日 02:00 (Asia/Taipei) 觸發，將「法顧成案清單」三個分頁推到 Supabase。
 *
 * ── 安裝步驟見 scripts/apps_script/SETUP.md ──
 *
 * Script Properties 需設：
 *   SUPABASE_URL          (例: https://zpbkeyhxyykbvownrngf.supabase.co)
 *   SUPABASE_SERVICE_KEY  (Supabase Settings → API → service_role key)
 */

// ============================================================
//  CONFIG
// ============================================================
const TAB_CASES    = '1. 業績成案清單';     // 第 1 個分頁的名稱（含前綴 "1. "）
const TAB_FUNNEL   = 'inbound數據';
const TAB_OUTBOUND = '電話陌開促成拜訪進度';

// 業績成案清單 欄位對應（A=1, B=2, ...）
const COL_CASES = {
  client_name: 1,        // A
  case_reason: 2,        // B
  source_category: 3,    // C
  client_source: 4,      // D
  is_signed: 5,          // E
  amount_paid: 6,        // F
  paid_at: 7,            // G
  salesperson: 8,        // H
  office: 9,             // I
  first_contact_at: 10,  // J
  consultation_lawyer_closed: 11, // K
  handling_lawyers: 12,  // L
  weight_no: 29,         // AC
  weight_excl: 30,       // AD
  weight_other: 31       // AE
};

// inbound 數據 欄位對應
const COL_FUNNEL = {
  month_label: 1,            // A 例 "2023/10月" 或 "11月"
  referral_faling: 2,        // B 法零轉介
  referral_pre_retain: 3,    // C 委前轉介
  notes_referral: 4,         // D 備註（公司名清單）
  refused_line: 5,           // E
  line_only: 6,              // F
  meeting_phone: 7,          // G
  meeting_video: 8,          // H
  meeting_onsite: 9,         // I
  signed: 10,                // J
  paid: 11,                  // K
  notes_remark: 12           // L
};

// 電話陌開 欄位對應
const COL_OUTBOUND = {
  seq: 1, brand: 2, account: 3, region: 4, company_name: 5,
  contact_phone: 6, has_conflict_check: 7, attended: 8,
  visited_at: 9, case_summary: 10, remark: 11, is_retained: 12, advisor_window: 13
};

// ============================================================
//  ENTRY POINTS
// ============================================================

/** 主同步入口：每日由 trigger 呼叫，也可手動執行 */
function syncAll() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  syncCases(ss);
  syncFunnel(ss);
  syncOutbound(ss);
}

/** 設定每日 02:00 觸發器（手動執行一次即可） */
function setupDailyTrigger() {
  // 移除舊的 syncAll trigger
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'syncAll') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncAll')
    .timeBased()
    .atHour(2).everyDays(1)
    .inTimezone('Asia/Taipei')
    .create();
  Logger.log('每日 02:00 trigger 設定完成');
}

// ============================================================
//  SYNC: 業績成案清單 → advisor_cases
// ============================================================
function syncCases(ss) {
  const startedAt = new Date();
  const sheet = ss.getSheetByName(TAB_CASES);
  if (!sheet) { logSync(TAB_CASES, 0, 0, 0, '找不到分頁: ' + TAB_CASES, startedAt); return; }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) { logSync(TAB_CASES, 0, 0, 0, '無資料列', startedAt); return; }

  const range = sheet.getRange(2, 1, lastRow - 1, 31).getValues();
  const rows = [];
  // 客戶歷史出現次數（用來推導 case_seq + 續委任）
  const clientSeq = {};

  // 先排序：依 paid_at 由舊到新，否則 case_seq 不準
  const indexed = range.map((r, i) => ({ row: r, idx: i + 2 }))
    .filter(o => !isAggregateRow(o.row, 0))  // 跳過月小計列
    .filter(o => o.row[COL_CASES.client_name - 1]);  // 跳過空白列

  indexed.sort((a, b) => {
    const da = parseDate(a.row[COL_CASES.paid_at - 1]);
    const db = parseDate(b.row[COL_CASES.paid_at - 1]);
    return (da ? da.getTime() : Infinity) - (db ? db.getTime() : Infinity);
  });

  indexed.forEach(o => {
    const r = o.row;
    const clientName = String(r[COL_CASES.client_name - 1] || '').trim();
    if (!clientName) return;

    const sourceRaw = String(r[COL_CASES.source_category - 1] || '').trim();
    const clientSourceRaw = String(r[COL_CASES.client_source - 1] || '').trim();
    const seq = (clientSeq[clientName] || 0) + 1;
    clientSeq[clientName] = seq;

    const lawyersRaw = String(r[COL_CASES.handling_lawyers - 1] || '').trim();
    const lawyers = lawyersRaw ? lawyersRaw.split(/[\/、，,]/).map(s => s.trim()).filter(Boolean) : [];

    const weightFlags = [
      r[COL_CASES.weight_no - 1], r[COL_CASES.weight_excl - 1], r[COL_CASES.weight_other - 1]
    ].filter(Boolean).join(' / ');

    const category = resolveCategory(seq, sourceRaw, clientSourceRaw);

    rows.push({
      client_name: clientName,
      case_reason: nullIfEmpty(r[COL_CASES.case_reason - 1]),
      source_category_raw: sourceRaw || null,
      client_source_raw: clientSourceRaw || null,
      is_signed: toBool(r[COL_CASES.is_signed - 1]),
      amount_paid: toNum(r[COL_CASES.amount_paid - 1]),
      paid_at: toDateStr(r[COL_CASES.paid_at - 1]),
      salesperson: nullIfEmpty(r[COL_CASES.salesperson - 1]),
      office: nullIfEmpty(r[COL_CASES.office - 1]),
      first_contact_at: toDateStr(r[COL_CASES.first_contact_at - 1]),
      consultation_lawyer_closed: toBool(r[COL_CASES.consultation_lawyer_closed - 1]),
      handling_lawyers: lawyers,
      weight_flags: weightFlags || null,
      case_seq_for_client: seq,
      case_category: category,
      sheet_row_index: o.idx,
      row_hash: hashRow([clientName, r[COL_CASES.paid_at - 1], r[COL_CASES.amount_paid - 1], sourceRaw, clientSourceRaw])
    });
  });

  // 全量替換策略：DELETE all → INSERT all
  const del = supabaseRequest('DELETE', '/rest/v1/advisor_cases?id=neq.00000000-0000-0000-0000-000000000000', null);
  const ins = batchInsert('/rest/v1/advisor_cases', rows);

  logSync(TAB_CASES, rows.length, 0, 0, ins.error || del.error || null, startedAt);
}

// ============================================================
//  SYNC: inbound 數據 → advisor_inbound_funnel
// ============================================================
function syncFunnel(ss) {
  const startedAt = new Date();
  const sheet = ss.getSheetByName(TAB_FUNNEL);
  if (!sheet) { logSync(TAB_FUNNEL, 0, 0, 0, '找不到分頁: ' + TAB_FUNNEL, startedAt); return; }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) { logSync(TAB_FUNNEL, 0, 0, 0, '無資料列', startedAt); return; }

  const range = sheet.getRange(2, 1, lastRow - 1, 12).getValues();
  const rows = [];
  let currentYear = null;

  range.forEach(r => {
    const label = String(r[0] || '').trim();
    if (!label) return;

    // 年度標頭列（如 "2023" 或 "2024"）
    const yearMatch = label.match(/^(\d{4})$/);
    if (yearMatch) { currentYear = parseInt(yearMatch[1], 10); return; }

    // 月份列：可能是 "2023/10月"、"10月"、"11月"
    let m = label.match(/^(\d{4})\/(\d{1,2})月/);
    let year, month;
    if (m) { year = parseInt(m[1], 10); month = parseInt(m[2], 10); }
    else {
      m = label.match(/^(\d{1,2})月/);
      if (!m || !currentYear) return;
      year = currentYear; month = parseInt(m[1], 10);
    }
    if (!year || !month || month < 1 || month > 12) return;

    rows.push({
      fiscal_year: year,
      month: month,
      referral_faling:     toNum(r[COL_FUNNEL.referral_faling - 1]),
      referral_pre_retain: toNum(r[COL_FUNNEL.referral_pre_retain - 1]),
      refused_line:        toNum(r[COL_FUNNEL.refused_line - 1]),
      line_only:           toNum(r[COL_FUNNEL.line_only - 1]),
      meeting_phone:       toNum(r[COL_FUNNEL.meeting_phone - 1]),
      meeting_video:       toNum(r[COL_FUNNEL.meeting_video - 1]),
      meeting_onsite:      toNum(r[COL_FUNNEL.meeting_onsite - 1]),
      signed:              toNum(r[COL_FUNNEL.signed - 1]),
      paid:                toNum(r[COL_FUNNEL.paid - 1]),
      notes_referral:      nullIfEmpty(r[COL_FUNNEL.notes_referral - 1]),
      notes_remark:        nullIfEmpty(r[COL_FUNNEL.notes_remark - 1])
    });
  });

  const del = supabaseRequest('DELETE', '/rest/v1/advisor_inbound_funnel?id=neq.00000000-0000-0000-0000-000000000000', null);
  const ins = batchInsert('/rest/v1/advisor_inbound_funnel', rows);

  logSync(TAB_FUNNEL, rows.length, 0, 0, ins.error || del.error || null, startedAt);
}

// ============================================================
//  SYNC: 電話陌開 → advisor_outbound_visits
// ============================================================
function syncOutbound(ss) {
  const startedAt = new Date();
  const sheet = ss.getSheetByName(TAB_OUTBOUND);
  if (!sheet) { logSync(TAB_OUTBOUND, 0, 0, 0, '找不到分頁: ' + TAB_OUTBOUND, startedAt); return; }

  const lastRow = sheet.getLastRow();
  if (lastRow < 3) { logSync(TAB_OUTBOUND, 0, 0, 0, '無資料列', startedAt); return; }

  // 跳過 row 1 (header) + row 2 (範例列)
  const range = sheet.getRange(3, 1, lastRow - 2, 13).getValues();
  const rows = [];
  range.forEach((r, i) => {
    const company = String(r[COL_OUTBOUND.company_name - 1] || '').trim();
    if (!company) return;
    rows.push({
      seq: toIntOrNull(r[COL_OUTBOUND.seq - 1]),
      brand: nullIfEmpty(r[COL_OUTBOUND.brand - 1]),
      account: nullIfEmpty(r[COL_OUTBOUND.account - 1]),
      region: nullIfEmpty(r[COL_OUTBOUND.region - 1]),
      company_name: company,
      contact_phone: nullIfEmpty(r[COL_OUTBOUND.contact_phone - 1]),
      has_conflict_check: toBool(r[COL_OUTBOUND.has_conflict_check - 1]),
      attended: toBool(r[COL_OUTBOUND.attended - 1]),
      visited_at: toDateStr(r[COL_OUTBOUND.visited_at - 1]),
      case_summary: nullIfEmpty(r[COL_OUTBOUND.case_summary - 1]),
      remark: nullIfEmpty(r[COL_OUTBOUND.remark - 1]),
      is_retained: toBool(r[COL_OUTBOUND.is_retained - 1]),
      advisor_window: nullIfEmpty(r[COL_OUTBOUND.advisor_window - 1]),
      sheet_row_index: i + 3,
      row_hash: hashRow([company, r[COL_OUTBOUND.visited_at - 1], r[COL_OUTBOUND.is_retained - 1]])
    });
  });

  const del = supabaseRequest('DELETE', '/rest/v1/advisor_outbound_visits?id=neq.00000000-0000-0000-0000-000000000000', null);
  const ins = batchInsert('/rest/v1/advisor_outbound_visits', rows);

  logSync(TAB_OUTBOUND, rows.length, 0, 0, ins.error || del.error || null, startedAt);
}

// ============================================================
//  CATEGORY RULES (C+D 合併)
// ============================================================
function resolveCategory(seq, sourceRaw, clientSourceRaw) {
  // 1. 同公司第 2 次以後 → 續委任
  if (seq >= 2) return '續委任';

  const d = String(clientSourceRaw || '');
  const c = String(sourceRaw || '');

  if (/續委任/.test(c)) return '續委任';
  if (/舊客|回頭|再委/.test(d) || /舊客|回頭|再委/.test(c)) return '續委任';
  if (/法顧客戶|法顧.*員工|法顧.*陪偵|法顧.*陪訊/.test(d)) return '舊客衍生';
  if (/諮詢後續|諮詢轉/.test(d)) return '諮詢轉案';
  if (/人脈|介紹|轉介/.test(d) || /人脈/.test(c)) return '人脈轉介';
  if (/^自行進線/.test(d.replace(/\s/g,''))) return '自行進線新案';
  if (/新案/.test(c)) return '自行進線新案';
  return '未分類';
}

// ============================================================
//  HELPERS
// ============================================================
function isAggregateRow(row, _) {
  // 月小計列特徵：A 欄是 "2023/8>> 43.2w" 這種格式（含 ">>"）且其他欄空
  const a = String(row[0] || '');
  return />>/.test(a);
}
function toBool(v) {
  if (v === true || v === 'TRUE' || v === '是' || v === 'Y' || v === 1) return true;
  if (v === false || v === '' || v == null || v === 'FALSE' || v === '否') return false;
  return null;
}
function toNum(v) {
  if (v == null || v === '') return 0;
  const n = Number(String(v).replace(/[,\s]/g, ''));
  return isNaN(n) ? 0 : n;
}
function toIntOrNull(v) {
  if (v == null || v === '') return null;
  const n = parseInt(v, 10);
  return isNaN(n) ? null : n;
}
function nullIfEmpty(v) {
  if (v == null) return null;
  const s = String(v).trim();
  return s === '' ? null : s;
}
function toDateStr(v) {
  const d = parseDate(v);
  if (!d) return null;
  return Utilities.formatDate(d, 'Asia/Taipei', 'yyyy-MM-dd');
}
function parseDate(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  const s = String(v).trim();
  if (!s) return null;
  // Try yyyy-mm-dd or yyyy/mm/dd
  let m = s.match(/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})/);
  if (m) return new Date(parseInt(m[1]), parseInt(m[2])-1, parseInt(m[3]));
  return null;
}
function hashRow(arr) {
  const s = arr.map(x => String(x == null ? '' : x)).join('|');
  return Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, s)
    .map(b => (b < 0 ? b + 256 : b).toString(16).padStart(2, '0'))
    .join('');
}

// ============================================================
//  SUPABASE REST
// ============================================================
function getProps() {
  const p = PropertiesService.getScriptProperties();
  const url = p.getProperty('SUPABASE_URL');
  const key = p.getProperty('SUPABASE_SERVICE_KEY');
  if (!url || !key) throw new Error('Script Properties 缺少 SUPABASE_URL 或 SUPABASE_SERVICE_KEY');
  return { url: url.replace(/\/+$/, ''), key: key };
}

function supabaseRequest(method, path, body) {
  const { url, key } = getProps();
  const opts = {
    method: method.toLowerCase(),
    headers: {
      'apikey': key,
      'Authorization': 'Bearer ' + key,
      'Content-Type': 'application/json',
      'Prefer': 'return=minimal'
    },
    muteHttpExceptions: true
  };
  if (body != null) opts.payload = JSON.stringify(body);
  const resp = UrlFetchApp.fetch(url + path, opts);
  const code = resp.getResponseCode();
  if (code >= 200 && code < 300) return { ok: true, error: null };
  return { ok: false, error: `${code}: ${resp.getContentText().slice(0, 500)}` };
}

function batchInsert(path, rows) {
  if (!rows.length) return { ok: true, error: null };
  const CHUNK = 200;
  let lastErr = null;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const chunk = rows.slice(i, i + CHUNK);
    const r = supabaseRequest('POST', path, chunk);
    if (!r.ok) lastErr = r.error;
  }
  return { ok: !lastErr, error: lastErr };
}

function logSync(tab, inserted, updated, deleted, error, startedAt) {
  const finishedAt = new Date();
  const body = [{
    sheet_tab: tab,
    rows_inserted: inserted, rows_updated: updated, rows_deleted: deleted,
    error_message: error,
    started_at: startedAt.toISOString(),
    finished_at: finishedAt.toISOString()
  }];
  supabaseRequest('POST', '/rest/v1/advisor_sync_log', body);
  Logger.log(`[${tab}] inserted=${inserted} error=${error || '-'}`);
}
