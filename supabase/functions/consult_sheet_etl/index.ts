// Supabase Edge Function: consult_sheet_etl
//
// Apps Script → 這個 Edge Function → Supabase（內部用 service_role）
//
// 為什麼需要：新版 secret_key 偵測 browser-like 環境會擋掉，Apps Script 不能直連 REST。
//
// Body:
//   {
//     "table": "consult_oa_monthly_funnel" | "consult_staff_monthly_sessions" | "consult_consultations",
//     "rows": [...],
//     "on_conflict": "oa_code,month_start"  // PK columns for UPSERT
//   }
//
// 安全：JWT 驗證關著（Edge Functions 預設關，部署時注意），但檢查 X-ETL-Secret header

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const ETL_SECRET = Deno.env.get('SHEET_ETL_SECRET') || '';

// Whitelist：只允許這些表，避免被當成通用寫入後門
const ALLOWED_TABLES = new Set([
  'consult_oa_monthly_funnel',
  'consult_staff_monthly_sessions',
  'consult_consultations',
  'consult_brand_monthly_outcomes',
]);

serve(async (req) => {
  try {
    // 1. 共用 secret 檢查
    if (ETL_SECRET) {
      const got = req.headers.get('X-ETL-Secret') || '';
      if (got !== ETL_SECRET) {
        return jsonResp({ ok: false, error: 'unauthorized' }, 401);
      }
    }

    // 2. parse body
    const body = await req.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return jsonResp({ ok: false, error: 'invalid body' }, 400);
    }

    const { table, rows, on_conflict } = body as {
      table?: string;
      rows?: any[];
      on_conflict?: string;
    };

    if (!table || !ALLOWED_TABLES.has(table)) {
      return jsonResp({ ok: false, error: `table not allowed: ${table}` }, 400);
    }
    if (!Array.isArray(rows) || rows.length === 0) {
      return jsonResp({ ok: false, error: 'rows must be non-empty array' }, 400);
    }

    // 3. UPSERT 用 service_role
    const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      auth: { persistSession: false },
    });

    // Supabase JS upsert 一次最多 ~1000 列；分批
    const CHUNK = 500;
    let inserted = 0;
    const errors: string[] = [];
    for (let i = 0; i < rows.length; i += CHUNK) {
      const chunk = rows.slice(i, i + CHUNK);
      const upsertOpts = on_conflict ? { onConflict: on_conflict } : {};
      const { error } = await supabase.from(table).upsert(chunk, upsertOpts);
      if (error) {
        errors.push(`chunk ${i / CHUNK}: ${error.message}`);
      } else {
        inserted += chunk.length;
      }
    }

    if (errors.length > 0) {
      return jsonResp({
        ok: false,
        inserted,
        total: rows.length,
        errors,
      }, 500);
    }

    return jsonResp({ ok: true, inserted, total: rows.length }, 200);
  } catch (e) {
    return jsonResp({
      ok: false,
      stage: 'top_level',
      error: String(e).slice(0, 300),
    }, 500);
  }
});

function jsonResp(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
