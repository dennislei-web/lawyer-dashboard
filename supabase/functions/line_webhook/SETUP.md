# LINE Webhook 設定步驟

3 個追蹤 OA 共用同一個 Edge Function endpoint。每個 OA 都要跑一遍步驟 1-3。

## 1. 在 LINE Developers Console 取得 Channel Secret + chatUrlPrefix

每個 OA 有一個 Messaging API channel：

1. 登入 https://developers.line.biz/console/
2. 選擇對應的 Provider → 進到 Messaging API channel
3. **Basic settings** → 複製 **Channel secret**
4. 取得 `chatUrlPrefix`（chat.line.biz URL 第一段，OA 後台管理 ID）：
   - 登入 https://manager.line.biz/，切到該 OA → 隨便開一段對話
   - 看網址 `chat.line.biz/{這段}/chat/...` → 第一段就是 `chatUrlPrefix`
   - **注意**：這個值 ≠ webhook body 的 `destination`（兩者都 `U` 開頭但不相等），不要混用

## 2. 設定 Supabase Edge Function Secret

全部 3 組資訊整理成一個 JSON，存進 Supabase：

```bash
supabase secrets set LINE_OA_CONFIG='[
  {"chatUrlPrefix":"Uxxxxxxxxxxxx1","secret":"xxxxx","name":"喆律法律事務所"},
  {"chatUrlPrefix":"Uxxxxxxxxxxxx2","secret":"xxxxx","name":"金貝殼"},
  {"chatUrlPrefix":"Uxxxxxxxxxxxx3","secret":"xxxxx","name":"85010"}
]'
```

`name` 會顯示在 dashboard 的「待人工綁定」清單，建議用法務看得懂的簡稱。

## 3. 設定 Webhook URL

每個 OA 的 Messaging API channel 裡：

1. **Messaging API** tab → **Webhook settings**
2. Webhook URL 填：`https://zpbkeyhxyykbvownrngf.supabase.co/functions/v1/line_webhook`
3. **Use webhook** 打開
4. **Verify** 按鈕試一下，應該顯示 Success（200 OK）— 若失敗先看 `supabase functions logs line_webhook`
5. **Auto-reply messages** 保持**開啟**（客戶加好友時仍然收到你們原本的歡迎訊息，webhook 是額外加的，不衝突）

## 4. 部署 Edge Function

```bash
cd supabase
supabase functions deploy line_webhook --no-verify-jwt
```

`--no-verify-jwt` 很重要：LINE 不會帶 Supabase 的 JWT，Edge Function 預設會拒絕。我們改用 LINE 的 x-line-signature 驗證。

## 5. 驗證

1. 用個人 LINE 加其中一個 OA 為好友
2. 檢查 `line_pending_bindings` 是否新增一筆 `matched_case_id IS NULL` 的 row
3. 回一則訊息（用 consultation_cases 裡某個未成案客戶名字）
4. 若 30 天內有唯一符合的未成案 → `matched_case_id` 被填上、`consultation_cases.line_chat_url` 被寫入
5. 否則該 row 留在 dashboard「待人工綁定」清單等法務處理

## Debug

```bash
# 看最近 log
supabase functions logs line_webhook --tail

# 手動清掉一筆 pending（service role）
delete from line_pending_bindings where user_id = 'Uxxx' and oa_id = 'Uxxx';
```
