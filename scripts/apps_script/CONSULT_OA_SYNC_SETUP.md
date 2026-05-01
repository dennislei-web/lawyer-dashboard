# 委前漏斗 ETL #2 — Apps Script 安裝 SOP

把 `consult_oa_monthly_sync.gs` 接到「委前各項數據追蹤表單」上，每週一 09:00 自動把「各帳號進線及場次數據統計表」分頁同步到 Supabase `consult_oa_monthly_funnel`。

> 預估時間：5 分鐘
> 前提：「委前各項數據追蹤表單」這張 Sheet 你有編輯權

---

## 一、開啟 Apps Script 編輯器

1. 開啟 Google Sheet「委前各項數據追蹤表單」
2. 上方選單 → **擴充功能** → **Apps Script**
3. 跳出新分頁，預設有一個 `Code.gs`

## 二、貼上程式碼

1. 預設 `Code.gs` 全部刪掉
2. 把 `scripts/apps_script/consult_oa_monthly_sync.gs` 全文複製貼進去
3. 左上角專案名改成 `consult-funnel-sync`（可選）
4. **儲存**（Ctrl+S）

## 三、設定 Script Properties

1. 編輯器左側 → 齒輪 **專案設定**
2. 滾到下方 **指令碼屬性** → 按 **新增指令碼屬性**
3. 新增兩筆：

   | 屬性名稱 | 值 |
   |---|---|
   | `SUPABASE_URL` | `https://zpbkeyhxyykbvownrngf.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | Supabase Settings → API Keys → `secret_key` 那把（bxw 開頭那個就行） |

4. 按 **儲存指令碼屬性**

> 註：用新版 secret_key（bxw 開頭）就可以，因為這是直接打 Supabase REST API，不像 Edge Function 那邊需要 JWT 格式。

## 四、第一次執行（授權 + 全量 backfill）

1. 編輯器頂端的函式選單選 **`syncOAMonthlyFunnel`**
2. 按 **▶ 執行**
3. 跳出「授權」對話框 → 用你的 Google 帳號授權（會請求讀取 Sheet + 對外 fetch 兩個權限）
4. 看左下角「執行記錄」應該看到：

   ```
   解析出 N 列 (oa_code × month)
   UPSERT 完成: {"ok":true,"count":N,"status":201}
   ```

   N 大概會是 2024 + 2025 + 2026/01-04 ≈ 14 OA × 28 個月 ≈ 350-400 筆。

5. 跳到 Supabase SQL Editor 驗證：

   ```sql
   SELECT COUNT(*) FROM consult_oa_monthly_funnel;
   SELECT oa_code, COUNT(*) AS months_recorded,
          MIN(month_start), MAX(month_start)
   FROM consult_oa_monthly_funnel
   GROUP BY oa_code ORDER BY oa_code;
   ```

   應該每個 active OA（除 FL）都看到 ~28 個月的資料。

## 五、設定每週自動觸發

1. 函式選單選 **`setupOAMonthlyWeeklyTrigger`**
2. 按 **▶ 執行**（這次不再需要授權）
3. 「執行記錄」會看到 `每週一 09:00 trigger 設定完成`
4. 左側選單「觸發器」確認有一筆 `syncOAMonthlyFunnel` 每週一 09:00 的排程

## 六、驗證設定無誤

跑這個查詢看 sample 資料：

```sql
SELECT oa_code, month_start, sessions, leads,
       ROUND((sessions::NUMERIC / NULLIF(leads, 0)) * 100, 1) AS sched_pct
FROM consult_oa_monthly_funnel
WHERE oa_code = 'FA' AND month_start >= '2026-01-01'
ORDER BY month_start;
```

預期結果（對照 sheet 上 2026 區塊的 FA 那行）：

| month_start | sessions | leads | sched_pct |
|---|---|---|---|
| 2026-01-01 | 73 | 531 | 13.7 |
| 2026-02-01 | 57 | 514 | 11.1 |
| 2026-03-01 | 74 | 473 | 15.6 |
| 2026-04-01 | 64 | 232 | 27.6 |

對得起來就完工 ✓

---

## 排錯

### Apps Script 跑出 `Supabase UPSERT 失敗 401`
service key 錯了。Properties 那邊重貼一次，注意是 secret_key 不是 publishable_key。

### `Supabase UPSERT 失敗 409` 或 `42P10`
表還沒建。先去 Supabase 跑 `consult_funnel_schema` migration（之前已經跑過的話這不會發生）。

### `Supabase UPSERT 失敗 23503` (foreign key violation)
代表 sheet 裡有未知 oa_code（不在 consult_oa_master）。`KNOWN_OA_CODES` 應該已過濾，若仍出現 = sheet 多了新 OA。看 Logger 印出哪個 oa_code 被「跳過」，再決定是新增到 master 還是擴 KNOWN_OA_CODES。

### `沒有資料可同步`
Sheet 名稱對不到。確認分頁名是「各帳號進線及場次數據統計表」沒有錯字。
