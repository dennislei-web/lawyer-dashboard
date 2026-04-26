-- 一次性清理：把 line_pending_bindings.last_extracted_name 落在 NAME_BLOCKLIST 的清成 NULL
-- 背景：webhook 早期版本沒擋「感謝/okok/好的」這類 ack 詞，會把客戶第一次傳的真姓名覆寫成這些短語。
-- 真姓名已不可救（DB 無歷史），但至少先讓 dashboard 不再顯示誤導名字；法務看 last_message_text 自行判斷。
-- 之後 webhook 改成 freeze（一旦抓到就不再覆寫），此清理只需執行一次。
UPDATE line_pending_bindings
SET last_extracted_name = NULL
WHERE LOWER(last_extracted_name) IN (
  -- 中文 ack / 客氣 / 短回應
  '感謝','謝謝','感恩','多謝','謝啦',
  '收到','了解','知道','明白','清楚',
  '好的','好喔','好啊','好吧','好啦','好哦','好滴','好低',
  '可以','不會','不用','沒事','不錯','可以的',
  '沒問題','不客氣',
  '是的','對的','不是','對啊','對對',
  '嗯嗯','哦哦','喔喔','哈哈','呵呵','欸欸','誒誒',
  '哈囉','哈摟','你好','您好',
  '抱歉','不好意思',
  '辛苦','辛苦了','晚安','早安','午安','再見','掰掰','拜拜',
  '麻煩','請問','想問','不好',
  '稍等','等等','稍候','加油',
  -- 英文 ack
  'ok','okok','okay','okie','okies',
  'yes','yeah','yep','yup','yea','ya','yo',
  'no','nope','nah',
  'hi','hii','hello','helo','hey',
  'thx','ty','tks','thanks','thank',
  'bye','byebye',
  'sure','fine','good','great','nice',
  'lol','hmm','hmmm','oops'
);
