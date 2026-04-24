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
let OA_PARSE_ERROR: string | null = null;
try {
  const parsed = JSON.parse(OA_CONFIG_RAW);
  if (!Array.isArray(parsed)) throw new Error('not an array');
  OA_LIST = parsed.filter(e => e && typeof e.secret === 'string' && typeof e.chatUrlPrefix === 'string');
  if (OA_LIST.length === 0) {
    // 注意：不能直接印 key 名，因為用戶可能把 secret 填在 key 位置會洩漏
    const shapes = parsed.map((e: any) => {
      if (!e || typeof e !== 'object') return 'non-object';
      const keys = Object.keys(e);
      return `{${keys.length} keys, hasSecret=${'secret' in e}, hasPrefix=${'chatUrlPrefix' in e}, hasName=${'name' in e}}`;
    }).join(' | ');
    OA_PARSE_ERROR = `parsed ${parsed.length} entries but 0 valid. shapes=${shapes}`;
  }
} catch (e) {
  OA_PARSE_ERROR = `parse failed: ${(e as Error).message} (raw len=${OA_CONFIG_RAW.length}, first char=${JSON.stringify(OA_CONFIG_RAW[0])})`;
  console.error('LINE_OA_CONFIG', OA_PARSE_ERROR);
}

const MATCH_WINDOW_DAYS = 30;

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

// 從客戶訊息抓姓名。只在以下 pattern 才認，避免抓到閒聊訊息前 2-4 字誤判：
//  1. 明確句型：「我是XXX」「我叫XXX」「敝姓X」「姓名：XXX」
//  2. 單純短訊息：純 2-4 字中文，可接結尾標點/emoji（例如「陸德」「陸德！」）
//  3. 客氣 lead-in + 短姓名：「您好 陸德」「你好，我是陸德」
// 其他情況（長句子、含問號、夾雜數字英文）一律回 null
function extractName(text: string): string | null {
  if (!text) return null;
  let s = text.trim();

  // 剝掉常見 lead-in（您好/你好/Hi/Hello + 標點）
  s = s.replace(/^(您好|你好|hi|hello)[\s,，、!！.。~～]*/i, '');
  // 剝掉自介句首（我是/我叫/敝姓/姓名是/名字是）
  s = s.replace(/^(我是|我叫|敝姓|在下|本人|本人是|姓名(?:是|:|：)|名字(?:是|:|：))[\s,，、]*/i, '');
  // 剝掉尾端標點
  s = s.replace(/[\s!！。?？~～,，、.…]+$/, '').trim();

  // 剝完之後剩下的必須「整串就是 2-4 字中文」才算名字
  if (/^[\u4e00-\u9fff]{2,4}$/.test(s)) return s;

  // fallback：全英文姓名（極罕見但保留，例如「Jill」「Stanley」）
  if (/^[A-Za-z]{2,20}$/.test(s)) return s;

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

  // 已 match 過 → 純更新 last_message 就結束
  if (existing?.matched_case_id) {
    await sb.from('line_pending_bindings')
      .update({ last_message_at: messageAt, last_message_text: text.slice(0, 500) })
      .eq('user_id', userId).eq('oa_id', oaKey);
    return;
  }

  const name = extractName(text);

  // 沒 pending row 且訊息不是短姓名 → silent ignore（避免閒聊訊息塞爆清單）
  if (!existing && !name) return;

  // 有名字才 match
  const followedAt = existing?.followed_at ?? messageAt;
  const candidates = name ? await tryAutoMatch(sb, name, followedAt) : [];

  // 沒 pending row 且名字對不到任何案件 → silent ignore（排除「好的感謝」這種 4 字短語）
  if (!existing && candidates.length === 0) return;

  // 到這裡：要嘛已有 row（更新），要嘛是 name + 至少 1 個 candidate（新建）
  if (!existing) {
    const { error: insErr } = await sb
      .from('line_pending_bindings')
      .insert({
        user_id: userId,
        oa_id: oaKey,
        oa_name: oa.name ?? null,
        followed_at: messageAt,
        last_message_at: messageAt,
        last_message_text: text.slice(0, 500),
        last_extracted_name: name,
        match_attempts: 1,
      });
    if (insErr) {
      console.error('pending insert error', insErr);
      return;
    }
  }

  // 不做 auto-bind 寫 consultation_cases.line_chat_url：
  // webhook event.source.userId 跟 chat.line.biz 後台用的 userId 不同，
  // 自動拼出來的 https://chat.line.biz/{prefix}/chat/{userId} 必定 404。
  // 所有 binding 一律由法務在 dashboard 看 last_message_text + extracted_name 後手動處理。

  // 不論 candidates 數量都只更新 last_message
  await sb.from('line_pending_bindings')
    .update({
      last_message_at: messageAt,
      last_message_text: text.slice(0, 500),
      last_extracted_name: name,
      match_attempts: (existing?.match_attempts ?? 0) + 1,
    })
    .eq('user_id', userId).eq('oa_id', oaKey);
}

serve(async (req) => {
  try {
    if (req.method !== 'POST') {
      return new Response('method not allowed', { status: 405 });
    }

    if (OA_PARSE_ERROR) {
      console.error('abort: config not loaded', OA_PARSE_ERROR);
      return new Response(`config error: ${OA_PARSE_ERROR}`, { status: 500 });
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
      console.warn('no secret matched signature', { sigLen: signature.length, oaCount: OA_LIST.length });
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
  } catch (err) {
    console.error('fatal', { err: String(err), stack: (err as Error)?.stack });
    return new Response(`fatal: ${String(err)}`, { status: 500 });
  }
});
