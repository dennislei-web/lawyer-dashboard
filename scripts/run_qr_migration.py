"""跑 quarterly_reviews 表的 migration"""
import httpx, os, io, sys
from dotenv import load_dotenv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]

MIGRATION_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "supabase", "migrations", "20260418000000_add_quarterly_reviews.sql",
)
with open(MIGRATION_PATH, encoding="utf-8") as f:
    sql = f.read()

# Use PostgREST RPC 'exec_sql' if available, else inform user to run in SQL Editor
# Supabase doesn't have a generic exec_sql RPC by default. So we'll try the Management API or
# instruct the user. Try a known pattern first: PostgreSQL query via supabase_admin (needs db password).
# Fallback: print the SQL for manual paste.

print("=" * 60)
print("  Supabase 沒有開放直接跑任意 SQL 的 REST endpoint")
print("  請複製以下 SQL 到 Supabase Dashboard 的 SQL Editor 執行：")
print("  https://supabase.com/dashboard/project/zpbkeyhxyykbvownrngf/sql")
print("=" * 60)
print()
print(sql)
print()
print("=" * 60)

# 驗證建好了沒
print("\n執行後跑這個 Python 再驗證：")
print("  python -c \"")
print("  import httpx, os; from dotenv import load_dotenv; load_dotenv()")
print("  H={'apikey':os.environ['SUPABASE_SERVICE_KEY'],'Authorization':'Bearer '+os.environ['SUPABASE_SERVICE_KEY']}")
print("  r=httpx.get(os.environ['SUPABASE_URL']+'/rest/v1/quarterly_reviews?limit=1', headers=H)")
print("  print(r.status_code, r.text[:200])\"")
