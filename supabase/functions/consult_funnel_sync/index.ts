// Supabase Edge Function: consult_funnel_sync
//
// 每日從 LINE Messaging API 拉每個 active OA 的 follower insight，
// UPSERT 到 consult_oa_funnel_daily。
//
// v2: 並行處理避免 timeout

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;

interface OACredential {
  oa_code: string;
  line_channel_token: string | null;
}

interface InsightRow {
  oa_code: string;
  insight_date: string;
  followers: number | null;
  targeted_reaches: number | null;
  blocks: number | null;
}

function ymdString(d: Date): { yyyymmdd: string; iso: string } {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return { yyyymmdd: `${y}${m}${dd}`, iso: `${y}-${m}-${dd}` };
}

async function callInsight(
  token: string,
  yyyymmdd: string,
): Promise<{ ok: boolean; status: number; body?: any; err?: string }> {
  try {
    const r = await fetch(
      `https://api.line.me/v2/bot/insight/followers?date=${yyyymmdd}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!r.ok) {
      const text = await r.text().catch(() => '');
      return { ok: false, status: r.status, err: text.slice(0, 200) };
    }
    return { ok: true, status: r.status, body: await r.json() };
  } catch (e) {
    return { ok: false, status: -1, err: String(e).slice(0, 200) };
  }
}

interface SyncResult {
  oa_code: string;
  dates_attempted: number;
  dates_ok: number;
  dates_failed: number;
  errors: string[];
}

async function syncOA(
  supabase: ReturnType<typeof createClient>,
  cred: OACredential,
  dates: { yyyymmdd: string; iso: string }[],
): Promise<SyncResult> {
  const result: SyncResult = {
    oa_code: cred.oa_code,
    dates_attempted: dates.length,
    dates_ok: 0,
    dates_failed: 0,
    errors: [],
  };

  if (!cred.line_channel_token) {
    result.errors.push('no token');
    result.dates_failed = dates.length;
    return result;
  }

  // 同一個 OA 的 N 個日期並行（LINE rate limit 很寬鬆）
  const responses = await Promise.all(
    dates.map((d) => callInsight(cred.line_channel_token!, d.yyyymmdd)),
  );

  const rows: InsightRow[] = [];
  responses.forEach((r, i) => {
    const d = dates[i];
    if (!r.ok) {
      result.dates_failed++;
      result.errors.push(
        `${d.iso}: status=${r.status} ${(r.err ?? '').slice(0, 80)}`,
      );
      return;
    }
    rows.push({
      oa_code: cred.oa_code,
      insight_date: d.iso,
      followers: r.body?.followers ?? null,
      targeted_reaches: r.body?.targetedReaches ?? null,
      blocks: r.body?.blocks ?? null,
    });
    result.dates_ok++;
  });

  if (rows.length === 0) return result;

  try {
    const { error } = await supabase
      .from('consult_oa_funnel_daily')
      .upsert(rows, { onConflict: 'oa_code,insight_date' });
    if (error) {
      result.errors.push(`upsert: ${error.message}`);
      result.dates_failed += result.dates_ok;
      result.dates_ok = 0;
    }
  } catch (e) {
    result.errors.push(`upsert exception: ${String(e).slice(0, 100)}`);
    result.dates_failed += result.dates_ok;
    result.dates_ok = 0;
  }

  return result;
}

serve(async (req) => {
  try {
    const url = new URL(req.url);
    const backfillDays = Math.max(
      1,
      Math.min(60, Number(url.searchParams.get('backfill_days') ?? '1')),
    );

    const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      auth: { persistSession: false },
    });

    const { data: creds, error: credErr } = await supabase
      .from('consult_oa_credentials')
      .select('oa_code, line_channel_token')
      .not('line_channel_token', 'is', null);
    if (credErr) {
      return new Response(
        JSON.stringify({ ok: false, stage: 'creds', error: credErr.message }),
        { status: 500, headers: { 'content-type': 'application/json' } },
      );
    }

    const { data: activeOas, error: maErr } = await supabase
      .from('consult_oa_master')
      .select('oa_code')
      .eq('status', 'active');
    if (maErr) {
      return new Response(
        JSON.stringify({ ok: false, stage: 'master', error: maErr.message }),
        { status: 500, headers: { 'content-type': 'application/json' } },
      );
    }

    const activeSet = new Set((activeOas ?? []).map((r) => r.oa_code));
    const targets = (creds ?? []).filter((c) =>
      activeSet.has(c.oa_code),
    ) as OACredential[];

    // 拉的日期：D-2 往前 backfill_days 天（LINE API 最新只到 D-2）
    const dates: { yyyymmdd: string; iso: string }[] = [];
    const today = new Date();
    for (let i = 2; i < 2 + backfillDays; i++) {
      const d = new Date(today.getTime() - i * 86400_000);
      dates.push(ymdString(d));
    }

    // OA 之間並行，每個 OA 內部也並行
    const results = await Promise.all(
      targets.map((t) =>
        syncOA(supabase, t, dates).catch((e) => ({
          oa_code: t.oa_code,
          dates_attempted: dates.length,
          dates_ok: 0,
          dates_failed: dates.length,
          errors: [`exception: ${String(e).slice(0, 100)}`],
        } as SyncResult)),
      ),
    );

    const summary = {
      ok: true,
      backfill_days: backfillDays,
      oa_count: targets.length,
      total_inserts: results.reduce((s, r) => s + r.dates_ok, 0),
      total_failures: results.reduce((s, r) => s + r.dates_failed, 0),
      per_oa: results.map((r) => ({
        oa_code: r.oa_code,
        ok: r.dates_ok,
        failed: r.dates_failed,
        ...(r.errors.length > 0 && { errors: r.errors }),
      })),
    };

    return new Response(JSON.stringify(summary, null, 2), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  } catch (e) {
    return new Response(
      JSON.stringify({
        ok: false,
        stage: 'top_level',
        error: String(e).slice(0, 300),
        stack: (e as Error)?.stack?.slice(0, 500),
      }),
      { status: 500, headers: { 'content-type': 'application/json' } },
    );
  }
});
