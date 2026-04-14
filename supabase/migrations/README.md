# Supabase Migrations

版本化的 SQL migration 檔案，檔名格式：`YYYYMMDDHHMMSS_description.sql`

## 執行方式

### 選項 1：Supabase Dashboard（目前使用）
1. 開啟 [Supabase SQL Editor](https://supabase.com/dashboard/project/zpbkeyhxyykbvownrngf/sql)
2. 依時間戳順序逐個執行 migration 檔案

### 選項 2：Supabase CLI（未來可考慮）
```bash
supabase db push
```

## Migration 清單

### 初始 Schema（2025-01）
- `20250101000000_initial_schema.sql` — 諮詢分析基礎表（lawyers, monthly_stats, consultation_logs）
- `20250101000100_seed.sql` — 初始 seed 資料
- `20250101000200_setup_all.sql` — 完整建置腳本（含 RLS、helper functions）

### 諮詢案件擴充
- `20250102000000_add_consultation_cases.sql` — 新增 consultation_cases 表
- `20250102000100_migrate_consultation_cases.sql` — 案件資料 migration
- `20250103000000_migrate_to_crm_fields.sql` — 對齊 CRM 爬蟲欄位
- `20250104000000_migrate_lawyer_notes.sql` — 律師備註欄
- `20250105000000_migrate_tracking_fields.sql` — 年度追蹤欄位
- `20250106000000_migrate_reset_password.sql` — 密碼重設支援
- `20250107000000_migrate_can_view_all.sql` — 全域查看權限
- `20250108000000_fix_rls_recursion.sql` — 修復 RLS 遞迴問題
- `20250109000000_add_sync_status.sql` — sync_status 表（同步狀態追蹤）

### 營運儀表板（2025-02）
- `20250201000000_revenue_schema.sql` — departments, revenue_records, monthly_revenue_stats 表 + RLS

### 財務規劃儀表板（2026-04）
- `20260413000000_finance_schema.sql` — finance_categories, finance_data, finance_adjustments, finance_employees, finance_uploads 表 + RLS + 科目 seed

## 注意事項

- 所有 migration 都是 idempotent（用 `CREATE TABLE IF NOT EXISTS`、`ON CONFLICT DO NOTHING` 等），重複執行不會出錯
- RLS 政策統一使用 `is_admin()` helper function（在 `20250201000000_revenue_schema.sql` 定義）
- 新增 migration 時使用當下的民國年月時間戳，確保執行順序正確
