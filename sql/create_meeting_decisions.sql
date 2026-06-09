-- 主管會議「歷次決議」表 + RLS（鏡像 meetings 的 is_admin 政策）
create table if not exists meeting_decisions (
  id uuid primary key default gen_random_uuid(),
  decided_date date,
  fiscal_year int,
  category text,
  title text not null,
  detail text,
  owner text,
  source_meeting_id uuid references meetings(id) on delete set null,
  sort_order int default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  updated_by uuid
);
alter table meeting_decisions enable row level security;
drop policy if exists meeting_decisions_admin on meeting_decisions;
create policy meeting_decisions_admin on meeting_decisions for all to public using (is_admin()) with check (is_admin());

-- 只在表為空時種子（可重複執行、不重覆、不覆蓋手動新增）
insert into meeting_decisions (decided_date,fiscal_year,category,title,detail,owner,source_meeting_id,sort_order)
select v.* from (values
('2025-02-03'::date,114,'獎金制度','諮詢獎金改為成案金額制（114/2/1 起）','取消每場 500 元；當月「諮詢委任金額(收款日為準)−退款」×3%；(委任金額−退款)/場次>3萬時整體升 5%；適用除所長外諮詢律師；未委任諮詢費不計、已委任計入（113/1/31 前已領 500 者不計）。','雷皓明、黃杰',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-02-03' limit 1),0),
('2025-01-06'::date,114,'獎金制度','續委任獎金制度正式上路','自 114Q1 起記錄；發放流程改為「主管確認→同仁確認→主管提供財務→財務發放」。','吳泰儀',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-01-06' limit 1),10),
('2025-08-05'::date,114,'獎金制度','續委任獎金適用範圍確定','實習律師通過試用期後適用、由主管律師分配 %；育嬰/當兵/工傷與大家同時發、其他留停回任後發。','各所',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-08-05' limit 1),20),
('2025-05-14'::date,114,'委後/客戶','委後 LINE 改用公用帳號','5/14 測試無誤後刪除主管私人 line，統一改用公用 line@（委前＋委後＋法顧）。','吳泰儀',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-05-14' limit 1),30),
('2025-10-14'::date,114,'系統/工程','專案管理系統權限治理上線','成員掛部門、財報/統計僅本部門可見、案件 CRUD 限本部門；權限清單 10/14 上線；工讀生權限由思蓓每週清。','何泓儒、吳泰儀',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-10-14' limit 1),40),
('2025-03-17'::date,114,'人資差勤','週日加班規範','週日加班須事先一週取得同仁「例假日/休息日互換」同意；平日 >4hr、23:00–07:00、週六加班均須事前申請。','各所',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-03-17' limit 1),50),
('2025-04-07'::date,114,'委前進線','利益衝突三段查核','委前安排時查一次、前一天再查、現場填資料再查；新人入職先檢索利衝再簽切結書。','何泓儒',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-04-07' limit 1),60),
('2025-07-08'::date,114,'系統/工程','轉案案件不分給合署律師','轉案的案件不分給合署律師，避免業績計算錯誤。','各所',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-07-08' limit 1),70),
('2025-07-08'::date,114,'委前進線','諮詢時間調整為 50 分鐘','諮詢時間由 1 小時改為 50 分鐘，每場間隔一小時。','委前',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-07-08' limit 1),80),
('2025-12-02'::date,114,'委前進線','品牌案件類型分類細化','侵害配偶權相關刑事/民事/協議書歸 85010，與婚姻無關者歸吉他（85010/金貝殼/吉他）。','何泓儒',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-12-02' limit 1),90),
('2025-02-17'::date,114,'委前進線','委前進線管道上線','Google 商家廣告、FastLaw 法速答上線；委前統一信箱回覆。','黃杰',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-02-17' limit 1),100),
('2025-09-09'::date,114,'知識庫/AI','AI 工具定案為 TaiLexi AI','改用 TaiLexi AI（hi@zhelu.tw），10/1 大會分享；使用場景：諮詢前分析、判決語意搜索、書狀初稿。','雷皓明、何泓儒',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2025-09-09' limit 1),110),
('2026-05-01'::date,115,'人資差勤','人資 EIP 考勤系統上線','5/1 起打卡/加班、5/6 起請假完整使用；主管每月至少第三週審核一次。','吳泰儀、人資',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2026-05-01' limit 1),120),
('2026-04-07'::date,115,'獎金制度','薪資結構年度調薪','35K 以下調至 35K、40K 以下 +5%、40K 以上 +3%；資深律師自案比例 7 同仁/3 事務所、事務所負擔稅務；續委任獎金維持；績效獎金 Q3-4 僅無續委任獎金者。','吳泰儀、雷皓明',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2026-04-07' limit 1),130),
('2026-05-12'::date,115,'獎金制度','續委任與諮詢獎金重複計算處理','續委任若新開系統會誤計入諮詢律師諮詢獎金 → 計算錯誤；過往不追回、向後處理（與飛宇確認）。','飛宇、何泓儒',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2026-05-12' limit 1),140),
('2026-03-13'::date,115,'行政/空間','主管活動日與春酒定案','3/13 主管活動日（卡爾登飯店/小樹屋 10:00–18:00）、3/14 春酒台中萊特薇庭。','吳泰儀',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2026-03-13' limit 1),150),
('2026-03-24'::date,115,'知識庫/AI','AI 教育訓練排程','3/27『打造你的 AI 特助』線上講座（偉利）、4/16 薩爾文 AI 陪跑課（小樹屋 20 人）。','吳泰儀',(select id from meetings where meeting_type='mgmt_weekly' and meeting_date='2026-03-24' limit 1),160)
) as v(decided_date,fiscal_year,category,title,detail,owner,source_meeting_id,sort_order)
where not exists (select 1 from meeting_decisions);
