// Supabase Edge Function: qa_ask
// 輸入律師的諮詢情境，先找既有相似 QA；沒命中再走 RAG（Voyage embed → match_case_chunks → Claude）。
// Runtime: Deno
// Deploy: supabase functions deploy qa_ask
// Secrets needed: VOYAGE_API_KEY, ANTHROPIC_API_KEY
//                 (SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY 由 Supabase runtime 自動注入)

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';
import Anthropic from 'https://esm.sh/@anthropic-ai/sdk@0.27.3';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const VOYAGE_KEY = Deno.env.get('VOYAGE_API_KEY')!;
const ANTHROPIC_KEY = Deno.env.get('ANTHROPIC_API_KEY')!;

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'authorization, content-type, apikey, x-client-info',
};

const CLAUDE_MODEL = 'claude-sonnet-4-5-20250929';
const EMBED_MODEL = 'voyage-law-2';
const QA_MATCH_THRESHOLD = 0.82;
const QA_MATCH_COUNT = 3;
const CHUNK_MATCH_COUNT = 8;

const SYSTEM_PROMPT = `你是一位資深法律諮詢對話顧問，專長是從律師過往諮詢實錄中歸納「面對特定客戶反應時的有效應對方式」。

任務：一位律師遇到某種諮詢情境不知道怎麼回應，請從全所過往諮詢語料中最相似的片段，歸納出具體、可直接使用的建議回覆。

規則：
1. 回覆必須基於提供的 chunks 原文。不要憑空生成律師沒說過的話。
2. 如果 chunks 中有多種回應風格，擇優整理並說明差異。
3. 如果 chunks 不足以回答，誠實說「找到的案例不夠相似，建議律師用 XX 原則自行發揮」。
4. 產出格式必須為合法 JSON（無 markdown 包裝），欄位：
   {
     "answer": "給律師的具體建議回覆（2-4 段，可直接參考使用）",
     "reasoning": "你從哪些片段、看到什麼 pattern 推出這個建議（2-3 句）",
     "cited_chunk_ids": ["實際有用到的片段 id，從 user message 給的 id 欄位抓"],
     "suggested_tags": ["最多 3 個中文 tag，例如：費用質疑、時程焦慮、處理細節、決策延遲"]
   }`;

function buildUserPrompt(scenario: string, chunks: any[]): string {
  const chunkBlocks = chunks.map((ch, i) => `
[片段 ${i + 1}] (id: ${ch.id})
案件：${ch.case_date} · ${ch.case_type ?? '未填'} · 客戶 ${ch.client_name ?? '未填'} · 律師 ${ch.lawyer_name ?? '未填'}
來源：${ch.source_type}
內容：
"""
${ch.content}
"""`).join('\n---\n');

  return `律師遇到的情境：
"""
${scenario}
"""

以下是全所過往諮詢語料中語意最相似的 ${chunks.length} 個片段：
${chunkBlocks}

請以 JSON 回覆，遵守 system prompt 指定的 schema。`;
}

async function embedQuery(text: string): Promise<number[]> {
  const resp = await fetch('https://api.voyageai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${VOYAGE_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input: [text],
      model: EMBED_MODEL,
      input_type: 'query',
    }),
  });
  if (!resp.ok) {
    const errTxt = await resp.text();
    throw new Error(`Voyage embed failed ${resp.status}: ${errTxt}`);
  }
  const json = await resp.json();
  return json.data[0].embedding;
}

function extractJson(text: string): any {
  // Claude 偶爾包 ```json ... ```，或前後有說明文字。抓第一個 { 到最後一個 }。
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start === -1 || end === -1) throw new Error('no JSON object in Claude output');
  return JSON.parse(text.slice(start, end + 1));
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS });
  }

  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'method not allowed' }), {
      status: 405,
      headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
    });
  }

  try {
    const authHeader = req.headers.get('Authorization');
    if (!authHeader) {
      return Response.json({ error: 'unauthorized: missing Authorization header' },
        { status: 401, headers: CORS_HEADERS });
    }

    // 用 user JWT client 驗 auth（但 RPC/INSERT 用 service client 繞 RLS 以便一致性）
    const sbUser = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      global: { headers: { Authorization: authHeader } },
      auth: { persistSession: false },
    });
    const { data: userData, error: userErr } = await sbUser.auth.getUser();
    if (userErr || !userData.user) {
      return Response.json({ error: 'unauthorized: invalid JWT' },
        { status: 401, headers: CORS_HEADERS });
    }

    // 查 lawyer_id（asked_by 要寫這個，不是 auth.uid()）
    const { data: lawyerRow, error: lawyerErr } = await sbUser
      .from('lawyers')
      .select('id, name')
      .eq('auth_user_id', userData.user.id)
      .single();
    if (lawyerErr || !lawyerRow) {
      return Response.json({ error: 'no lawyer profile for this user' },
        { status: 403, headers: CORS_HEADERS });
    }

    const body = await req.json().catch(() => ({}));
    const scenario: string = (body.scenario ?? '').trim();
    if (scenario.length < 5 || scenario.length > 300) {
      return Response.json(
        { error: 'scenario must be 5-300 characters', length: scenario.length },
        { status: 400, headers: CORS_HEADERS },
      );
    }

    // 1. 用 service client 之後所有 DB 呼叫（繞 RLS），但 insert 時 asked_by 手動填 lawyer_row.id
    const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
      auth: { persistSession: false },
    });

    // 2. Embed scenario
    const embedding = await embedQuery(scenario);

    // 3. 先搜既有 QA（題 4：同樣問題直接貼）
    const { data: matches, error: matchErr } = await sb.rpc('match_qa_entries', {
      query_embedding: embedding,
      match_threshold: QA_MATCH_THRESHOLD,
      match_count: QA_MATCH_COUNT,
    });
    if (matchErr) {
      console.error('match_qa_entries error', matchErr);
    }

    if (matches && matches.length > 0) {
      return Response.json({
        type: 'reused',
        matches,
      }, { headers: CORS_HEADERS });
    }

    // 4. 沒命中 → RAG over case_chunks
    const { data: chunks, error: chunkErr } = await sb.rpc('match_case_chunks', {
      query_embedding: embedding,
      match_count: CHUNK_MATCH_COUNT,
    });
    if (chunkErr) {
      console.error('match_case_chunks error', chunkErr);
      return Response.json({ error: 'retrieval failed', details: chunkErr.message },
        { status: 500, headers: CORS_HEADERS });
    }

    if (!chunks || chunks.length === 0) {
      return Response.json({
        type: 'no_context',
        message: '目前語料庫中沒有可供參考的片段。請先跑過 embedding backfill。',
      }, { headers: CORS_HEADERS });
    }

    // 5. 呼叫 Claude
    const claude = new Anthropic({ apiKey: ANTHROPIC_KEY });
    const claudeResp = await claude.messages.create({
      model: CLAUDE_MODEL,
      max_tokens: 2000,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: buildUserPrompt(scenario, chunks) }],
    });

    const rawText = claudeResp.content[0].type === 'text' ? claudeResp.content[0].text : '';
    let parsed: any;
    try {
      parsed = extractJson(rawText);
    } catch (e) {
      console.error('parse claude output failed', rawText);
      return Response.json({
        error: 'claude returned non-JSON',
        raw: rawText.slice(0, 500),
      }, { status: 500, headers: CORS_HEADERS });
    }

    // 6. 存 qa_entry
    const citedIds: string[] = Array.isArray(parsed.cited_chunk_ids) ? parsed.cited_chunk_ids : [];
    const tags: string[] = Array.isArray(parsed.suggested_tags) ? parsed.suggested_tags.slice(0, 3) : [];

    const { data: inserted, error: insertErr } = await sb
      .from('qa_entries')
      .insert({
        asked_by: lawyerRow.id,
        scenario,
        scenario_embedding: embedding,
        ai_answer: parsed.answer ?? '',
        ai_reasoning: parsed.reasoning ?? '',
        source_chunk_ids: citedIds,
        tags,
      })
      .select('id')
      .single();

    if (insertErr) {
      console.error('insert qa_entry failed', insertErr);
      // 即使存失敗，還是把答案回給律師
    }

    // 只把實際 cited 的 chunk 送回前端，減少 payload
    const citedChunks = chunks.filter((c: any) => citedIds.includes(c.id));
    const fallbackChunks = citedChunks.length > 0 ? citedChunks : chunks.slice(0, 3);

    return Response.json({
      type: 'new',
      qa_id: inserted?.id ?? null,
      answer: parsed.answer ?? '',
      reasoning: parsed.reasoning ?? '',
      cited_chunks: fallbackChunks,
      tags,
      tokens_used: {
        input: claudeResp.usage.input_tokens,
        output: claudeResp.usage.output_tokens,
      },
    }, { headers: CORS_HEADERS });

  } catch (err) {
    console.error('qa_ask fatal', err);
    return Response.json({ error: String(err?.message ?? err) },
      { status: 500, headers: CORS_HEADERS });
  }
});
