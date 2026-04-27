// Supabase Edge Function: trigger_sync
// 從儀表板手動觸發 GitHub Actions 的「每日更新諮詢統計」workflow。
// Runtime: Deno
// Deploy: supabase functions deploy trigger_sync
// Secrets needed:
//   GITHUB_TOKEN  - fine-grained PAT，scope=Actions:write on dennislei-web/lawyer-dashboard
//   GITHUB_REPO   - "dennislei-web/lawyer-dashboard"
//   GITHUB_WORKFLOW_FILE - 預設 "update-stats.yml"，可省略
//   (SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY 由 runtime 自動注入)

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const GITHUB_TOKEN = Deno.env.get('GITHUB_TOKEN') ?? '';
const GITHUB_REPO = Deno.env.get('GITHUB_REPO') ?? '';
const GITHUB_WORKFLOW_FILE = Deno.env.get('GITHUB_WORKFLOW_FILE') ?? 'update-stats.yml';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'authorization, content-type, apikey, x-client-info',
};

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS });
  }
  if (req.method !== 'POST') {
    return Response.json({ error: 'method not allowed' }, { status: 405, headers: CORS_HEADERS });
  }

  try {
    if (!GITHUB_TOKEN || !GITHUB_REPO) {
      return Response.json(
        { error: 'GITHUB_TOKEN / GITHUB_REPO Edge Function secret 未設定' },
        { status: 500, headers: CORS_HEADERS },
      );
    }

    const authHeader = req.headers.get('Authorization');
    if (!authHeader) {
      return Response.json({ error: 'unauthorized: missing Authorization header' },
        { status: 401, headers: CORS_HEADERS });
    }

    const sbUser = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      global: { headers: { Authorization: authHeader } },
      auth: { persistSession: false },
    });
    const { data: userData, error: userErr } = await sbUser.auth.getUser();
    if (userErr || !userData.user) {
      return Response.json({ error: 'unauthorized: invalid JWT' },
        { status: 401, headers: CORS_HEADERS });
    }

    const { data: lawyerRow, error: lawyerErr } = await sbUser
      .from('lawyers')
      .select('id, name, role')
      .eq('auth_user_id', userData.user.id)
      .single();
    if (lawyerErr || !lawyerRow) {
      return Response.json({ error: 'no lawyer profile for this user' },
        { status: 403, headers: CORS_HEADERS });
    }
    if (lawyerRow.role !== 'admin' && lawyerRow.role !== 'manager') {
      return Response.json({ error: 'forbidden: 僅 admin/manager 可觸發同步' },
        { status: 403, headers: CORS_HEADERS });
    }

    const body = await req.json().catch(() => ({}));
    const months = typeof body.months === 'string' ? body.months : '';
    const month = typeof body.month === 'string' ? body.month : '';

    // 用 service client 預先寫一筆 running，前端就不用等 GH runner 啟動才有畫面變化
    const sbAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      auth: { persistSession: false },
    });
    const nowIso = new Date().toISOString();
    await sbAdmin.from('sync_status').upsert({
      id: 'daily_update',
      status: 'running',
      message: `${lawyerRow.name} 手動觸發中...`,
      scraped_months: months || month || '',
      rows_scraped: 0,
      rows_updated: 0,
      started_at: nowIso,
      finished_at: null,
      updated_at: nowIso,
    });

    // 觸發 GitHub workflow_dispatch
    const dispatchUrl =
      `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW_FILE}/dispatches`;
    const inputs: Record<string, string> = {};
    if (month) inputs.month = month;
    if (months) inputs.months = months;

    const ghResp = await fetch(dispatchUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs }),
    });

    if (ghResp.status !== 204) {
      const errTxt = await ghResp.text();
      // 寫回 error 狀態，避免 UI 一直停在 running
      await sbAdmin.from('sync_status').upsert({
        id: 'daily_update',
        status: 'error',
        message: `觸發 GitHub workflow 失敗 (HTTP ${ghResp.status})`,
        finished_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      return Response.json(
        { error: 'github dispatch failed', status: ghResp.status, details: errTxt.slice(0, 500) },
        { status: 502, headers: CORS_HEADERS },
      );
    }

    return Response.json(
      { ok: true, triggered_by: lawyerRow.name, inputs },
      { status: 202, headers: CORS_HEADERS },
    );
  } catch (err) {
    console.error('trigger_sync fatal', err);
    return Response.json({ error: String((err as Error)?.message ?? err) },
      { status: 500, headers: CORS_HEADERS });
  }
});
