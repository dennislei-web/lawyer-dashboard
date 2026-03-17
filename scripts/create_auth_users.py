"""
create_auth_users.py
批次在 Supabase Auth 建立使用者，並自動綁定到 lawyers 表。

使用方式：
  python create_auth_users.py

會讀取 lawyers 表中 auth_user_id 為 NULL 的律師，
為每位律師建立 Auth 使用者並回寫 auth_user_id。

環境變數：
  SUPABASE_URL=https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY=eyJxxxxxxxxx
  DEFAULT_PASSWORD=初始密碼（律師首次登入後應修改）
"""

import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "ChangeMe123!")


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 取得尚未綁定 auth 的律師
    resp = supabase.table("lawyers").select("id, name, email").is_("auth_user_id", "null").execute()
    lawyers = resp.data

    if not lawyers:
        print("所有律師都已綁定 Auth 帳號")
        return

    print(f"找到 {len(lawyers)} 位律師需要建立帳號：")

    for lawyer in lawyers:
        print(f"  建立帳號：{lawyer['name']} ({lawyer['email']}) ...", end=" ")
        try:
            auth_resp = supabase.auth.admin.create_user({
                "email": lawyer["email"],
                "password": DEFAULT_PASSWORD,
                "email_confirm": True,  # 跳過 email 驗證
            })
            auth_user_id = auth_resp.user.id

            # 回寫 auth_user_id
            supabase.table("lawyers").update({
                "auth_user_id": auth_user_id
            }).eq("id", lawyer["id"]).execute()

            print(f"✓ (uid: {auth_user_id})")
        except Exception as e:
            print(f"✗ {e}")

    print(f"\n初始密碼：{DEFAULT_PASSWORD}")
    print("請通知律師登入後修改密碼")


if __name__ == "__main__":
    main()
