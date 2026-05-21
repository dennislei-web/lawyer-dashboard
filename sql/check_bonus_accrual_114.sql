-- 查 114年「薪資支出(年終預估)」月別實際數
-- 用途：確認 12月 19.2M 是 source P&L 真的有，還是匯入過程加上去的
SELECT
  fc.name AS category,
  fd.month,
  fd.amount,
  fd.data_type,
  fd.updated_at
FROM finance_data fd
JOIN finance_categories fc ON fc.id = fd.category_id
WHERE fc.name LIKE '%年終%'
  AND fd.fiscal_year = 114
  AND fd.data_type = 'actual'
ORDER BY fc.name, fd.month;
