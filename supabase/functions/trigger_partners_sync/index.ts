// Supabase Edge Function: trigger_partners_sync
// 從 partners 儀表板手動觸發 GitHub Actions 的「合署律師資料同步」workflow。
// Runtime: Deno
// Deploy:  supabase functions deploy trigger_partners_sync
//
// Secrets needed (同 trigger_sync 共用)：
//   GITHUB_TOKEN  - fine-grained PAT，scope=Actions:write on dennislei-web/lawyer-dashboard
//   GITHUB_REPO   - "dennislei-web/lawyer-dashboard"
//   (SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY 由 runtime 自動注入)

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const GITHUB_TOKEN = Deno.env.get('GITHUB_TOKEN') ?? '';
const GITHUB_REPO = Deno.env.get('GITHUB_REPO') ?? '';
const WORKFLOW_FILE = 'sync-partners.yml';

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
    // diagnostic：印 shape 不印 value
    if (!GITHUB_TOKEN || !GITHUB_REPO) {
      return Response.json(
        {
          error: 'Edge Function secret 未設定',
          missing: {
            GITHUB_TOKEN: !GITHUB_TOKEN,
            GITHUB_REPO: !GITHUB_REPO,
          },
        },
        { status: 500, headers: CORS_HEADERS },
      );
    }

    // ---- 認證 ----
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
    // partners 儀表板現在限定 admin
    if (lawyerRow.role !== 'admin') {
      return Response.json({ error: 'forbidden: 僅 admin 可觸發合署律師資料同步' },
        { status: 403, headers: CORS_HEADERS });
    }

    // ---- 觸發 GitHub workflow_dispatch ----
    const dispatchUrl =
      `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

    const ghResp = await fetch(dispatchUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: {} }),
    });

    if (ghResp.status !== 204) {
      const errTxt = await ghResp.text();
      return Response.json(
        {
          error: 'github dispatch failed',
          status: ghResp.status,
          details: errTxt.slice(0, 500),
        },
        { status: 502, headers: CORS_HEADERS },
      );
    }

    return Response.json(
      {
        ok: true,
        triggered_by: lawyerRow.name,
        message: '已觸發。請等 2-3 分鐘讓 Action 跑完 + GitHub Pages 部署，再重新整理頁面。',
        actions_url: `https://github.com/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}`,
      },
      { status: 202, headers: CORS_HEADERS },
    );
  } catch (err) {
    console.error('trigger_partners_sync fatal', err);
    return Response.json({ error: String((err as Error)?.message ?? err) },
      { status: 500, headers: CORS_HEADERS });
  }
});
