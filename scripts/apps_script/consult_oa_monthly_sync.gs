/**
 * 委前漏斗 ETL #2: 各帳號進線及場次數據統計表 → consult_oa_monthly_funnel
 *
 * 資料源：「委前各項數據追蹤表單」中的「各帳號進線及場次數據統計表」分頁
 * 目標：Supabase consult_oa_monthly_funnel
 *
 * 觸發方式：
 *   - 手動跑 syncOAMonthlyFunnel()（首次 backfill）
 *   - 每週一 09:00 自動跑（setupOAMonthlyWeeklyTrigger() 一次性設定）
 *
 * Script Properties 需設：
 *   SUPABASE_URL          (例: https://zpbkeyhxyykbvownrngf.supabase.co)
 *   SHEET_ETL_SECRET      (與 Edge Function consult_sheet_etl 設的 SHEET_ETL_SECRET 相同)
 *
 * 為何走 Edge Function：新版 Supabase secret key 會擋掉「browser-like」環境（含 Apps Script），
 * 必須由 Edge Function 內部用 service_role 中繼。
 *
 * 安裝步驟見 CONSULT_OA_SYNC_SETUP.md
 */

// ============================================================
//  CONFIG
// ============================================================
const SHEET_ID = '1aQO1tc1rpzg9DsWQTW4YQg56Hp5vdz8w2clzlUDU5YY';
const TAB_OA_STATS = '各帳號進線及場次數據統計表';

// 該分頁的欄位 layout（已確認過）：
//   col 0:    oa_code
//   col 1:    廣告對應名稱
//   col 3M-1: month M 場次       (M = 1..12)
//   col 3M  : month M 進線
//   col 3M+1: month M 比例 (%)   ← 我們不存，用視圖計算
//
// 每年一個區塊，年份 label 在該區塊第 1 列的 col 2 ("2024" / "2025" / "2026")。

// 既知有效的 OA codes（僅這些會被寫入；其他略過）
const KNOWN_OA_CODES = new Set([
  'FA', '1FA', '2FA', '3FA', '4FA', '5FA', '6FA',
  'MB', '1MB', '2MB', '3MB', '4MB',
  'Z', '1Z',
  'FL',  // FL 雖然 paused，留著容錯
]);

// ============================================================
//  ENTRY POINTS
// ============================================================

/** 主入口：手動跑 / trigger 跑都呼叫這個 */
function syncOAMonthlyFunnel() {
  const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(TAB_OA_STATS);
  if (!sheet) throw new Error(`找不到分頁: ${TAB_OA_STATS}`);

  const data = sheet.getDataRange().getValues();
  const rows = parseOAStats_(data);
  Logger.log(`解析出 ${rows.length} 列 (oa_code × month)`);

  if (rows.length === 0) {
    Logger.log('沒有資料可同步');
    return { ok: true, count: 0 };
  }

  // 印 sample 列協助除錯
  Logger.log(`sample: ${JSON.stringify(rows.slice(0, 2))}`);

  const result = upsertViaEdgeFunction_('consult_oa_monthly_funnel', rows, 'oa_code,month_start');
  Logger.log(`UPSERT 完成: ${JSON.stringify(result)}`);
  return result;
}

/** 設每週一 09:00 觸發 */
function setupOAMonthlyWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'syncOAMonthlyFunnel') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncOAMonthlyFunnel')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(9)
    .inTimezone('Asia/Taipei')
    .create();
  Logger.log('每週一 09:00 trigger 設定完成');
}

// ============================================================
//  PARSER
// ============================================================

/**
 * 解析 sheet 2D array → long-format rows
 * Returns: [{ oa_code, month_start, sessions, leads, source }]
 */
function parseOAStats_(data) {
  const out = [];
  let currentYear = null;

  for (let r = 0; r < data.length; r++) {
    const row = data[r];

    // 偵測年份標籤：col 2 是 4 位數年份的 row
    const c2 = String(row[2] || '').trim();
    if (/^20\d{2}$/.test(c2)) {
      currentYear = parseInt(c2, 10);
      continue;
    }

    if (!currentYear) continue;

    const oaCode = String(row[0] || '').trim();
    if (!oaCode) continue;
    // 跳過 header 列、total 列
    if (oaCode === 'LINE@帳號別' || oaCode.includes('total') || oaCode.includes('Total')) continue;
    if (!KNOWN_OA_CODES.has(oaCode)) {
      Logger.log(`跳過未知 oa_code: ${oaCode}`);
      continue;
    }

    // 拉 12 個月的資料
    for (let m = 1; m <= 12; m++) {
      const sessions = toIntOrNull_(row[3 * m - 1]);
      const leads = toIntOrNull_(row[3 * m]);

      // 兩個都是 null 視為沒資料；任一個有值就寫入
      if (sessions === null && leads === null) continue;

      const monthStart = formatDate_(currentYear, m, 1);
      out.push({
        oa_code: oaCode,
        month_start: monthStart,
        sessions: sessions ?? 0,
        leads: leads ?? 0,
        source: 'sheet_apps_script',
      });
    }
  }
  return out;
}

function toIntOrNull_(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(String(v).replace(/[,%]/g, ''));
  if (!Number.isFinite(n)) return null;
  return Math.round(n);
}

function formatDate_(year, month, day) {
  const m = String(month).padStart(2, '0');
  const d = String(day).padStart(2, '0');
  return `${year}-${m}-${d}`;
}

// ============================================================
//  SUPABASE (via Edge Function consult_sheet_etl)
// ============================================================

function upsertViaEdgeFunction_(tableName, rows, onConflict) {
  const props = PropertiesService.getScriptProperties();
  const url = props.getProperty('SUPABASE_URL');
  const secret = props.getProperty('SHEET_ETL_SECRET');
  if (!url) {
    throw new Error('Script Properties 缺 SUPABASE_URL');
  }
  // SHEET_ETL_SECRET 可空（Edge Function 那邊也沒設就不檢查）
  // 但建議要設，防止其他人意外觸發

  const endpoint = `${url}/functions/v1/consult-etl`;
  const headers = { 'Content-Type': 'application/json' };
  if (secret) headers['X-ETL-Secret'] = secret;

  const opts = {
    method: 'post',
    headers: headers,
    payload: JSON.stringify({
      table: tableName,
      rows: rows,
      on_conflict: onConflict,
    }),
    muteHttpExceptions: true,
  };

  const resp = UrlFetchApp.fetch(endpoint, opts);
  const code = resp.getResponseCode();
  const body = resp.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error(`Edge Function 呼叫失敗 ${code}: ${body.slice(0, 300)}`);
  }
  return JSON.parse(body);
}
