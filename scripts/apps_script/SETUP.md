# 法律顧問儀表板 — Apps Script 安裝 SOP

把 `advisor_sync.gs` 裝到 Google Sheet「法顧成案清單」上，每天凌晨 02:00（台北時間）自動把資料同步到 Supabase，儀表板就會自動更新。

> 預估時間：5–8 分鐘
> 安裝者需具備：對該 Sheet 的編輯權 + Supabase 控制台的存取權

---

## 一、先決條件

執行 SQL migration 把資料表建好：

1. 開 Supabase Dashboard → 進入專案 `zpbkeyhxyykbvownrngf`
2. 左側選單 → **SQL Editor**
3. 貼上 `supabase/migrations/20260428000000_advisor_schema.sql` 全文（這份檔在儀表板專案裡），按 **Run**
4. 應該會看到 `Success. No rows returned`

> 已執行過的話這步可以跳過。

---

## 二、取得 Supabase service_role key

1. Supabase Dashboard → **Project Settings**（齒輪圖示）→ **API**
2. 找到 **Project API keys** 區塊
3. 複製 `service_role` 那一把（注意：**不是** `anon public`）— 這把繞過 RLS，**絕對不能放到前端程式碼**

---

## 三、把 Apps Script 裝到 Sheet

### 3.1 開啟 Apps Script 編輯器

1. 開啟 Google Sheet「法顧成案清單」
2. 上方選單 → **擴充功能** → **Apps Script**
3. 會跳出新分頁，預設有一個 `Code.gs`

### 3.2 貼上程式碼

1. 把預設的 `Code.gs` 內容**全部刪掉**
2. 把 `scripts/apps_script/advisor_sync.gs` 全文複製貼進去
3. 左上角檔名改成 `advisor_sync`（可選）
4. 按 **儲存**（Ctrl+S 或硬碟圖示）

### 3.3 設定 Script Properties（金鑰）

1. 編輯器左側 → 齒輪 **專案設定**（Project Settings）
2. 滾到下方 **指令碼屬性**（Script Properties）→ 按 **新增指令碼屬性**
3. 新增兩筆：

   | 屬性名稱 | 值 |
   |---|---|
   | `SUPABASE_URL` | `https://zpbkeyhxyykbvownrngf.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | （二、複製到的 service_role key）|

4. 按 **儲存指令碼屬性**

### 3.4 第一次手動執行（授權 + 測試）

1. 編輯器左側 → **編輯器**（< > 圖示）回到程式碼
2. 上方下拉選單選 `syncAll` → 按 **執行**
3. 第一次會跳出授權對話框：
   - 「您必須要擁有此權限才能執行此函式」→ 按 **檢視權限**
   - 選您的 Google 帳號
   - 「Google 尚未驗證這個應用程式」→ 點 **進階** → **前往「未命名專案」（不安全）**
   - 同意 Spreadsheet 讀取 + 外部 URL 連線權限
4. 授權完後會自動執行，看下方 **執行記錄**（View → Logs，或 Ctrl+Enter）
5. 應該看到：
   ```
   [1. 業績成案清單] inserted=N error=-
   [inbound數據]   inserted=N error=-
   [電話陌開促成拜訪進度] inserted=N error=-
   ```

### 3.5 設定每日自動執行

回到編輯器，下拉選單選 `setupDailyTrigger` → 按 **執行**

執行完成後到左側 **觸發程序**（鬧鐘圖示）確認有一筆：
- 函式：`syncAll`
- 事件：時間驅動 / 日計時器 / 凌晨 2 點到 3 點

---

## 四、驗證

1. Supabase Dashboard → **Table Editor**
2. 應該看到三張新表都有資料：
   - `advisor_cases`（每筆成案）
   - `advisor_inbound_funnel`（每月一列）
   - `advisor_outbound_visits`（拜訪清單）
   - `advisor_sync_log`（同步紀錄，每次同步寫一筆）
3. 開儀表板 https://dennislei-web.github.io/lawyer-dashboard/#/advisor — 上方「上次同步」應該顯示剛才的時間

---

## 五、後續維護

### 改 Sheet 欄位之後

`advisor_sync.gs` 開頭的 `COL_CASES` / `COL_FUNNEL` / `COL_OUTBOUND` 物件記載每個欄位對應的「欄號」（A=1, B=2...）。
如果在 Sheet 中插入或調動欄位，要同步修改這些常數，再 **儲存** Apps Script 就會生效。

### 看同步歷史 / 排錯

Supabase SQL Editor 跑：
```sql
SELECT * FROM advisor_sync_log ORDER BY started_at DESC LIMIT 20;
```
看每次同步的時間、寫入筆數、錯誤訊息。

如果 `error_message` 不為 null：
- `403`：service_role key 錯了，回二、重新複製
- `400`：Sheet 欄位順序變了，回 `COL_*` 對照表檢查
- 找不到分頁：分頁名稱被改了，回 `advisor_sync.gs` 開頭三個 `TAB_*` 常數修正

### 手動觸發同步

Apps Script 編輯器 → 下拉選 `syncAll` → 執行。

---

## 六、安全注意

- `SUPABASE_SERVICE_KEY` 是 **可以繞過所有權限做任何事** 的 master key
- 它只放在 Sheet 的 Script Properties（不在程式碼、不在 git）— 不要：
  - 把它複製到任何地方
  - 把 Apps Script 專案分享給外人
  - 在程式碼裡 `Logger.log` 印出 key 內容
- 如果不慎外洩 → Supabase Dashboard → API → Reset service_role key，並回三、3.3 更新 Script Properties
