# Supabase 設定指南

## 1. 建立 Supabase 專案

1. 前往 https://supabase.com 註冊/登入
2. 建立新專案（Free plan 即可）
3. 記下以下資訊：
   - **Project URL**: `https://xxxxx.supabase.co`
   - **anon (public) key**: 前端使用
   - **service_role key**: Python script 使用（不要暴露在前端！）

## 2. 建立資料表

1. 進入 Supabase Dashboard → SQL Editor
2. 依時間戳順序執行 `migrations/` 資料夾內的 SQL 檔案（可參考 `migrations/README.md`）
   - 初次建置：從 `20250101000000_initial_schema.sql` 開始依序執行
   - 新加入的 migration 也是按時間戳順序

## 3. 建立 Auth 使用者

在 Supabase Dashboard → Authentication → Users：

1. 點 "Add User" → "Create New User"
2. 輸入每位律師的 email 和初始密碼
3. 記下每位使用者的 UUID

## 4. 綁定 Auth 使用者到 lawyers 表

在 SQL Editor 執行：

```sql
-- 替換成實際的 UUID 和 email
UPDATE lawyers SET auth_user_id = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
WHERE email = 'wang@zhelv.com';
```

## 5. 設定環境變數

### 前端（.env）
```
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJxxxxxxxxx
```

### Python script（.env）
```
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
```

## 6. 驗證 RLS

登入律師帳號，確認只能看到自己的資料：
- 在 SQL Editor 用 `SET request.jwt.claims = ...` 測試
- 或直接在前端登入測試

## 7. 注意事項

- **service_role key** 有完全權限，繞過 RLS，只在 Python server 端使用
- **anon key** 受 RLS 保護，可安全放在前端
- 免費方案限制：500MB 資料庫、50MB 儲存、50,000 月活用戶（內部工具綽綽有餘）
