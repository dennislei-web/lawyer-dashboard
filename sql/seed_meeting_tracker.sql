-- ============================================================
--  Seed：3 場 2026 Q1 營運會議 + 5/18 股東會 + 23 個 action items
--  資料來源：drive-download 三場營運會議 docx + 喆律OKR.docx
--  可重跑 (NOT EXISTS guard)
-- ============================================================

-- ───────── 1. 4 場會議 ─────────
INSERT INTO meetings (meeting_date, meeting_type, title, attendees, summary)
SELECT * FROM (VALUES
  (DATE '2026-01-05', 'op_weekly',  '事務所營運討論',
     ARRAY['雷皓明','何泓儒','吳泰儀','黃杰'],
     'Q1 第一場營運週會，全部 actions 都是新增；確立諮詢規則、會議記錄優化等專案。'),
  (DATE '2026-01-12', 'op_weekly',  '事務所營運討論',
     ARRAY['雷皓明','何泓儒','吳泰儀','黃杰'],
     '主要是 carry-over：磊山合作折扣 1500 確認、會議記錄優化約 1/14 開會、漲價方案延後。'),
  (DATE '2026-02-04', 'op_weekly',  '事務所營運討論',
     ARRAY['雷皓明','何泓儒','吳泰儀','黃杰'],
     '春酒 3/13-15 確定萊特薇庭、薪資制度（資深改 73 自案）、育嬰留停年終算法、下午茶預算調升等新議題。'),
  (DATE '2026-05-18', 'shareholder', '2026 Q1-Q2 股東會',
     ARRAY['雷皓明','何泓儒','吳泰儀','黃杰'],
     '回顧 1-2 月 OKR 進度（KR1 諮詢營收落後、KR2 諮詢轉化偏低）。新議題：新竹所長變動、台南延長諮詢、官網英文上架、薩爾文 AI 教練團、員旅報名落後。')
) AS v(meeting_date, meeting_type, title, attendees, summary)
WHERE NOT EXISTS (
  SELECT 1 FROM meetings m
  WHERE m.meeting_date = v.meeting_date AND m.meeting_type = v.meeting_type
);

-- ───────── 2. 23 個 action items ─────────
-- 用 source_meeting_date + title 當 natural key 防重複
INSERT INTO meeting_action_items (
  source_meeting_id, title, category, kr_code, owner,
  status, next_review_date, carry_count, latest_resolution
)
SELECT
  (SELECT id FROM meetings WHERE meeting_date = v.smd AND meeting_type = v.smt),
  v.title, v.category, v.kr_code, v.owner,
  v.status, v.next_review, v.carry_count, v.latest_resolution
FROM (VALUES
  -- ─── 從 1/5 起跑的長期項目 ───
  (DATE '2026-01-05','op_weekly','林杰妹／里長線下諮詢 ─ 目標帶 160 場諮詢','法律010','kr1','何泓儒',
     'in_progress', DATE '2026-05-26', 4,
     '3/3 已啟動會議；2/26 嘉卿轉線下討論完畢；月薪 36k+20k／好友數 60 已設'),
  (DATE '2026-01-05','op_weekly','磊山合作工程進度','工程','kr1','何泓儒',
     'in_progress', DATE '2026-05-26', 3,
     '勞智答 landing 改、新申請磊山專屬帳號／諮詢折扣 1500 已上；工程進度待 emily 回覆'),
  (DATE '2026-01-05','op_weekly','孫律師寫書進度追蹤','合署','kr4','雷皓明',
     'blocked', DATE '2026-05-26', 4,
     '113 年介紹金額 238 萬／佣金 42.7；4 月會議 ＠黃 — 5/18 仍未 follow-up'),
  (DATE '2026-01-05','op_weekly','會議記錄優化（改用 NotebookLM）','工程','kr7','黃杰',
     'in_progress', DATE '2026-06-02', 3,
     '1/14 已開會（黃杰／思蓓／泓儒／emily）；Q1-Q2 思蓓先處理，未來改律師自行＋AI'),
  (DATE '2026-01-05','op_weekly','短影音廣告成效（雷律師預算）','法律010','kr1','何泓儒',
     'in_progress', DATE '2026-05-26', 3,
     '每兩週一次會議；待整理已投放案件成案率'),
  (DATE '2026-01-05','op_weekly','3 月漲價預告 / 4 月漲到 3000/4000','客戶關係','kr1','何泓儒',
     'blocked', DATE '2026-05-26', 3,
     '已過時點，5/19 仍未漲 — 需決策放棄還是延後'),
  (DATE '2026-01-05','op_weekly','諮詢規則 / 律師獎金制度試算表','客戶關係','kr2','雷皓明',
     'pending', DATE '2026-05-26', 1,
     '1/5 提出，後續無 follow-up'),
  (DATE '2026-01-05','op_weekly','胡康邦合作 (1141016 已會議, 11/17 已簽約)','客戶關係','kr1','何泓儒',
     'done', NULL, 3,
     '11/17 已簽約完成'),
  (DATE '2026-01-05','op_weekly','TaiLex 合作 / 經銷 / 向量搜尋','工程',NULL,'黃杰',
     'in_progress', DATE '2026-05-26', 3,
     '1/12 會議：摘要格式三四種需一致；建置費 30 萬／維護費 1 萬／資料庫 $1500 月；報價中'),
  (DATE '2026-01-05','op_weekly','春酒 萊特薇庭 (3/14)','人資',NULL,'吳泰儀',
     'done', NULL, 3,
     '3/13(五) 主管 TB+晚上聚餐住宿、3/14(六) 春酒、3/15(日) 司法官律師 TB；已完成'),
  (DATE '2026-01-05','op_weekly','法零是否轉回喆律（台北刑案 / 台南高雄新竹）','法律010','kr5','何泓儒',
     'pending', DATE '2026-05-26', 3,
     '泓儒與明峰討論，目前無場次；週三上午拜訪'),
  (DATE '2026-01-05','op_weekly','宋、劉合作方案 (4 月會議@黃)','合署','kr4','黃杰',
     'pending', DATE '2026-05-26', 2,
     '4 月會議仍待安排'),

  -- ─── 從 2/4 起跑的單會議項目 ───
  (DATE '2026-02-04','op_weekly','下午茶預算調升（至少 60，希望 80）','人資',NULL,'吳泰儀',
     'pending', DATE '2026-05-26', 2,
     '2/4 首次提出'),
  (DATE '2026-02-04','op_weekly','育嬰留停年終比例計算（琬琪是否扣留停期間？）','人資',NULL,'吳泰儀',
     'pending', DATE '2026-05-26', 2,
     '是否拆兩階段薪資計算比例？'),
  (DATE '2026-02-04','op_weekly','過年前最後一天通過試用期者 $6000','人資',NULL,'吳泰儀',
     'done', NULL, 1,
     '已通過'),
  (DATE '2026-02-04','op_weekly','資深律師改 73 自案 / 資淺正常調整','人資',NULL,'吳泰儀',
     'in_progress', DATE '2026-05-26', 2,
     '所長／資深律師不調薪，改自案分配比例；資淺、法務正常調整'),
  (DATE '2026-02-04','op_weekly','法顧續委任會議（4 月開始）／對帳單系統建立','法顧','kr3','黃杰',
     'in_progress', DATE '2026-06-02', 1,
     '已委任客戶案件狀況開會確認；以已消耗時數計算獎金試算'),

  -- ─── 從 5/18 股東會起跑的新議題 ───
  (DATE '2026-05-18','shareholder','新竹所長變動 ─ 王庭 / 光星評估北所合署','合署','kr4','黃杰',
     'pending', DATE '2026-05-26', 1,
     '儘早找光星討論轉北所合署可能性，所長可能人選：王庭'),
  (DATE '2026-05-18','shareholder','台南所諮詢時間延長至晚上 7 點','客戶關係','kr1','雷皓明',
     'pending', DATE '2026-05-26', 1, NULL),
  (DATE '2026-05-18','shareholder','新竹芷羽加入諮詢 / 睿杰','人資','kr1','何泓儒',
     'pending', DATE '2026-05-26', 1,
     '短期先芷羽、睿杰加入；中期更換所長'),
  (DATE '2026-05-18','shareholder','移民講座 ─ PPT 準備 + 日期延後','客戶關係',NULL,'雷皓明',
     'pending', DATE '2026-05-26', 1,
     '5/6 建議延後，PPT 製作來回需更多時間'),
  (DATE '2026-05-18','shareholder','員旅 ─ 台南所、新竹所均 0 人參與','人資',NULL,'吳泰儀',
     'blocked', DATE '2026-05-26', 1, NULL),
  (DATE '2026-05-18','shareholder','薩爾文 AI 教練團 ─ 確認人數 + 各部門 AI 問題','工程','kr7','雷皓明',
     'pending', DATE '2026-05-26', 1,
     '股東四人＋偉志、珅維、jude，再加飛宇、思蓓、杰峰待確認；要釐清各自想解的問題'),
  (DATE '2026-05-18','shareholder','孫許律續委任金額給付','合署','kr4','雷皓明',
     'pending', DATE '2026-05-26', 1, NULL),
  (DATE '2026-05-18','shareholder','勞健保送資料 ─ 回報飛宇','財務',NULL,'吳泰儀',
     'pending', DATE '2026-05-26', 1, NULL),
  (DATE '2026-05-18','shareholder','官網英文上架 (3/23) + 4 月底改版','工程',NULL,'何泓儒',
     'in_progress', DATE '2026-05-26', 1,
     '3/23 周完成翻譯給律師審閱；官網改版四月底上架'),
  (DATE '2026-05-18','shareholder','與佳瑩討論（先專案方式，加薪 5000） / 過年前去當磊山秘密客','人資',NULL,'吳泰儀',
     'done', NULL, 1, '已決定')
) AS v(smd, smt, title, category, kr_code, owner, status, next_review, carry_count, latest_resolution)
WHERE NOT EXISTS (
  SELECT 1 FROM meeting_action_items a
  WHERE a.title = v.title
);

-- ───────── 3. Follow-up 歷史（讓老掛單能看到 timeline）─────────
-- 只為前 6 個 carry ≥ 3 的高優先項目補完整 timeline，其他單會議項目不需要
INSERT INTO action_followups (action_item_id, meeting_id, followup_date, status_before, status_after, resolution)
SELECT
  (SELECT id FROM meeting_action_items WHERE title = v.title),
  (SELECT id FROM meetings WHERE meeting_date = v.mdate AND meeting_type = v.mtype),
  v.mdate, v.before, v.after, v.resolution
FROM (VALUES
  -- 林杰妹 (4 場都出現)
  ('林杰妹／里長線下諮詢 ─ 目標帶 160 場諮詢', DATE '2026-01-12', 'op_weekly',  'pending',     'pending',     '無進度，繼續討論'),
  ('林杰妹／里長線下諮詢 ─ 目標帶 160 場諮詢', DATE '2026-02-04', 'op_weekly',  'pending',     'in_progress', '確認月薪 36k+20k，好友數 60'),
  ('林杰妹／里長線下諮詢 ─ 目標帶 160 場諮詢', DATE '2026-05-18', 'shareholder','in_progress', 'in_progress', '3/3 已啟動會議；2/26 嘉卿轉線下討論完畢'),

  -- 磊山 (3 場)
  ('磊山合作工程進度', DATE '2026-01-12', 'op_weekly', 'pending',     'in_progress', '確定折扣 1500、改新帳號'),
  ('磊山合作工程進度', DATE '2026-02-04', 'op_weekly', 'in_progress', 'in_progress', '過年前去當秘密客；工程待 emily 回覆'),

  -- 孫律 (4 場 — 完全沒進度)
  ('孫律師寫書進度追蹤', DATE '2026-01-12', 'op_weekly',  'pending',     'pending',  '未動'),
  ('孫律師寫書進度追蹤', DATE '2026-02-04', 'op_weekly',  'pending',     'blocked',  '4 月會議 ＠黃，待安排'),
  ('孫律師寫書進度追蹤', DATE '2026-05-18', 'shareholder','blocked',     'blocked',  '仍未開會 — 已逾期'),

  -- 會議記錄 NotebookLM (3 場)
  ('會議記錄優化（改用 NotebookLM）', DATE '2026-01-12', 'op_weekly', 'pending',     'in_progress', '已約 1/14 1730-1830'),
  ('會議記錄優化（改用 NotebookLM）', DATE '2026-02-04', 'op_weekly', 'in_progress', 'in_progress', '1/14 已開會（黃杰／思蓓／泓儒／emily）— 思蓓 Q1-Q2 先做'),

  -- 短影音 (3 場)
  ('短影音廣告成效（雷律師預算）', DATE '2026-01-12', 'op_weekly', 'pending',     'in_progress', '每兩週一次會議；預算成效再確認'),
  ('短影音廣告成效（雷律師預算）', DATE '2026-02-04', 'op_weekly', 'in_progress', 'in_progress', '待整理已投放案件成案率 ＠泓儒'),

  -- 漲價 (3 場 + 5/18 補一筆)
  ('3 月漲價預告 / 4 月漲到 3000/4000', DATE '2026-01-12', 'op_weekly', 'pending', 'pending', '同上未動'),
  ('3 月漲價預告 / 4 月漲到 3000/4000', DATE '2026-02-04', 'op_weekly', 'pending', 'pending', '同上未動'),
  ('3 月漲價預告 / 4 月漲到 3000/4000', DATE '2026-05-18', 'shareholder','pending','blocked', '已過時點 — 5/19 仍未漲，需決策'),

  -- 胡康邦 (3 場 done)
  ('胡康邦合作 (1141016 已會議, 11/17 已簽約)', DATE '2026-01-12', 'op_weekly', 'in_progress', 'done', '11/17 已簽約'),

  -- TaiLex (3 場)
  ('TaiLex 合作 / 經銷 / 向量搜尋', DATE '2026-01-12', 'op_weekly', 'pending',     'in_progress', '1/12 會議：摘要格式三四種需一致'),
  ('TaiLex 合作 / 經銷 / 向量搜尋', DATE '2026-02-04', 'op_weekly', 'in_progress', 'in_progress', '建置費 30 萬／維護費 1 萬／報價中'),

  -- 春酒 (3 場 done)
  ('春酒 萊特薇庭 (3/14)', DATE '2026-01-12', 'op_weekly', 'pending', 'in_progress', '萊特薇庭已訂位待簽約'),
  ('春酒 萊特薇庭 (3/14)', DATE '2026-02-04', 'op_weekly', 'in_progress', 'done', '3/13-15 完整安排確定')
) AS v(title, mdate, mtype, before, after, resolution)
WHERE NOT EXISTS (
  SELECT 1 FROM action_followups f
  WHERE f.action_item_id = (SELECT id FROM meeting_action_items WHERE title = v.title)
    AND f.followup_date = v.mdate
);
