// Supabase Edge Function: line_webhook
// 4 個追蹤 OA 共用同一個 endpoint，靠 body.destination 區分
// follow event → upsert line_pending_bindings
// message event → 若還沒 match，抓姓名試綁 consultation_cases
//
// Deploy: supabase functions deploy line_webhook --no-verify-jwt
//   （--no-verify-jwt 很重要：LINE 不會帶 Supabase JWT）
// Secrets: LINE_OA_CONFIG (JSON array, 見 SETUP.md)

import { serve } from 'https://deno.land/std@0.224.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.0';

const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
const SUPABASE_SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const OA_CONFIG_RAW = Deno.env.get('LINE_OA_CONFIG') ?? '[]';

// chatUrlPrefix = chat.line.biz/{這個}/chat/{userId} 的第一段（OA 後台管理 ID）
// dest = webhook body.destination（bot user ID，跟 chatUrlPrefix 不一樣但都 U 開頭）
// 初次部署時 dest 可能還沒知道，留空；function 會用「逐一試 secret」驗章，不靠 dest 路由
type OAEntry = { chatUrlPrefix: string; secret: string; name?: string; dest?: string };
let OA_LIST: OAEntry[] = [];
try {
  OA_LIST = JSON.parse(OA_CONFIG_RAW);
} catch (e) {
  console.error('LINE_OA_CONFIG parse failed', e);
}

const MATCH_WINDOW_DAYS = 14;

async function hmacSha256Base64(secret: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

// 從客戶訊息抓姓名：去 lead-in 後抓第一個 2-4 字中文連續字元
function extractName(text: string): string | null {
  if (!text) return null;
  let s = text.trim();
  s = s.replace(/^(您好|你好|hi|hello)[\s,，、!！.。]*/i, '');
  s = s.replace(/^(我是|我叫|敝姓|在下|本人)[\s,，、]*/i, '');
  s = s.trim();
  const cjk = s.match(/[\u4e00-\u9fff]{2,4}/);
  if (cjk) return cjk[0];
  // fallback：全英文且長度合理（極罕見但留著）
  if (s.length >= 2 && s.length <= 20 && /^[a-z\s]+$/i.test(s)) return s;
  return null;
}

function escapeLike(s: string): string {
  return s.replace(/[%_\\]/g, c => '\\' + c);
}

async function tryAutoMatch(
  sb: ReturnType<typeof createClient>,
  name: string,
  followedAt: string,
): Promise<Array<{ id: string; client_name: string; case_date: string }>> {
  const cutoff = new Date(new Date(followedAt).getTime() - MATCH_WINDOW_DAYS * 86400000)
    .toISOString().slice(0, 10);
  const { data, error } = await sb
    .from('consultation_cases')
    .select('id, client_name, case_date')
    .eq('is_signed', false)
    .ilike('client_name', `%${escapeLike(name)}%`)
    .gte('case_date', cutoff)
    .is('line_chat_url', null)                 // 排除已被其他管道綁過的
    .order('case_date', { ascending: false })
    .limit(5);
  if (error) {
    console.error('tryAutoMatch query error', error);
    return [];
  }
  return data ?? [];
}

async function handleFollow(sb: any, event: any, oa: OAEntry) {
  if (event.source?.type !== 'user') return;
  const userId = event.source.userId;
  const followedAt = new Date(event.timestamp).toISOString();
  // 存 oa_id = chatUrlPrefix（因為 dashboard 要用它拼 chat.line.biz URL）
  const { error } = await sb
    .from('line_pending_bindings')
    .upsert({
      user_id: userId,
      oa_id: oa.chatUrlPrefix,
      oa_name: oa.name ?? null,
      followed_at: followedAt,
    }, { onConflict: 'user_id,oa_id' });
  if (error) console.error('follow upsert error', error);
}

async function handleMessage(sb: any, event: any, oa: OAEntry) {
  if (event.source?.type !== 'user') return;
  if (event.message?.type !== 'text') return;       // 只處理文字訊息
  const userId = event.source.userId;
  const text: string = event.message.text ?? '';
  const messageAt = new Date(event.timestamp).toISOString();
  const oaKey = oa.chatUrlPrefix;

  // 抓現有 pending binding
  const { data: existing, error: selErr } = await sb
    .from('line_pending_bindings')
    .select('*')
    .eq('user_id', userId)
    .eq('oa_id', oaKey)
    .maybeSingle();
  if (selErr) {
    console.error('pending select error', selErr);
    return;
  }

  // 沒 follow 紀錄（例如 webhook 上線前就已加好友）→ 補建一筆用 messageAt 當 followed_at
  if (!existing) {
    const { error: upErr } = await sb
      .from('line_pending_bindings')
      .insert({
        user_id: userId,
        oa_id: oaKey,
        oa_name: oa.name ?? null,
        followed_at: messageAt,
        last_message_at: messageAt,
        last_message_text: text.slice(0, 500),
      });
    if (upErr) console.error('pending insert on message error', upErr);
  }

  const row = existing ?? { followed_at: messageAt, matched_case_id: null, match_attempts: 0 };

  // 已 match 過就不再動，純更新 last_message
  if (row.matched_case_id) {
    await sb.from('line_pending_bindings')
      .update({ last_message_at: messageAt, last_message_text: text.slice(0, 500) })
      .eq('user_id', userId).eq('oa_id', oaKey);
    return;
  }

  // 嘗試抓姓名
  const name = extractName(text);
  const candidates = name ? await tryAutoMatch(sb, name, row.followed_at) : [];

  const baseUpdate: Record<string, unknown> = {
    last_message_at: messageAt,
    last_message_text: text.slice(0, 500),
    last_extracted_name: name,
    match_attempts: (row.match_attempts ?? 0) + 1,
  };

  if (candidates.length === 1) {
    // 自動綁定：寫 consultation_cases.line_chat_url + 標記 pending 已 match
    const caseId = candidates[0].id;
    const chatUrl = `https://chat.line.biz/${oa.chatUrlPrefix}/chat/${userId}`;
    const { error: ccErr } = await sb
      .from('consultation_cases')
      .update({
        line_chat_url: chatUrl,
        line_chat_updated_at: new Date().toISOString(),
        line_chat_updated_by: null,    // auto，不歸屬任何律師
      })
      .eq('id', caseId)
      .is('line_chat_url', null);      // race: 不覆蓋已有連結

    if (ccErr) {
      console.error('auto-bind consultation update error', ccErr);
    } else {
      baseUpdate.matched_case_id = caseId;
      baseUpdate.matched_at = new Date().toISOString();
      baseUpdate.matched_by = 'auto';
    }
  }

  // 0 / >1 / 自動綁失敗 → 只更新累計欄位，留在 pending 表
  await sb.from('line_pending_bindings')
    .update(baseUpdate)
    .eq('user_id', userId).eq('oa_id', oaKey);
}

serve(async (req) => {
  if (req.method !== 'POST') {
    return new Response('method not allowed', { status: 405 });
  }

  const rawBody = await req.text();
  const signature = req.headers.get('x-line-signature') ?? '';

  // 逐一試 secret 驗章 — 哪把 secret 算出的簽章對得上，就是哪個 OA
  // 這樣不依賴 body.destination（實測 destination != chatUrlPrefix）
  let matchedOA: OAEntry | null = null;
  for (const entry of OA_LIST) {
    const expected = await hmacSha256Base64(entry.secret, rawBody);
    if (timingSafeEqual(signature, expected)) {
      matchedOA = entry;
      break;
    }
  }
  if (!matchedOA) {
    console.warn('no secret matched signature', { sigLen: signature.length });
    return new Response('bad signature', { status: 401 });
  }

  let payload: any;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response('invalid json', { status: 400 });
  }

  // 記下 LINE 實際 destination，方便之後 debug / 補 config
  if (payload.destination && payload.destination !== matchedOA.dest) {
    console.log('oa matched', {
      name: matchedOA.name, chatUrlPrefix: matchedOA.chatUrlPrefix,
      actualDestination: payload.destination,
    });
  }

  const oa = matchedOA;
  const events: any[] = Array.isArray(payload.events) ? payload.events : [];
  if (events.length === 0) {
    // LINE 驗證 webhook 時會送空 events，回 200 即可
    return new Response('ok', { status: 200 });
  }

  const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
    auth: { persistSession: false },
  });

  // 串行處理（events 數量通常很小；且 upsert 有 race 風險最好一筆一筆）
  for (const ev of events) {
    try {
      if (ev.type === 'follow') {
        await handleFollow(sb, ev, oa);
      } else if (ev.type === 'message') {
        await handleMessage(sb, ev, oa);
      }
      // unfollow / join / leave 等先忽略
    } catch (e) {
      console.error('event handler failed', { type: ev.type, err: String(e) });
      // 不中斷後面事件
    }
  }

  return new Response('ok', { status: 200 });
});
