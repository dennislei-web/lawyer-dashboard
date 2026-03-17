"""
setup_admin.py
建立管理員（雷皓明）的 Auth 帳號並綁定到 lawyers 表。
使用獨立的 supabase-auth 和 postgrest 套件，不需要完整 supabase SDK。
"""

import os

from dotenv import load_dotenv
from supabase_auth import SyncGoTrueClient
from postgrest import SyncPostgrestClient

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")


def main():
    # Auth client (admin)
    auth = SyncGoTrueClient(
        url=f"{SUPABASE_URL}/auth/v1",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )

    # DB client
    db = SyncPostgrestClient(
        base_url=f"{SUPABASE_URL}/rest/v1",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )

    # 1. 建立 Auth 使用者
    print(f"建立 Auth 帳號：{ADMIN_EMAIL} ...", end=" ")
    try:
        resp = auth.admin.create_user({
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "email_confirm": True,
        })
        auth_user_id = resp.user.id
        print(f"OK (uid: {auth_user_id})")
    except Exception as e:
        error_msg = str(e)
        if "already been registered" in error_msg or "already exists" in error_msg:
            print("帳號已存在，嘗試取得 uid ...")
            users_resp = auth.admin.list_users()
            auth_user_id = None
            for u in users_resp:
                if hasattr(u, '__iter__'):
                    for user in u:
                        if hasattr(user, 'email') and user.email == ADMIN_EMAIL:
                            auth_user_id = user.id
                            break
                elif hasattr(u, 'email') and u.email == ADMIN_EMAIL:
                    auth_user_id = u.id
                    break
            if auth_user_id:
                print(f"  找到 uid: {auth_user_id}")
            else:
                print(f"  無法取得 uid: {e}")
                return
        else:
            print(f"失敗: {e}")
            return

    # 2. 綁定到 lawyers 表
    print("綁定到 lawyers 表 ...", end=" ")
    try:
        db.from_("lawyers").update({"auth_user_id": str(auth_user_id)}).eq("email", ADMIN_EMAIL).execute()
        print("OK")
    except Exception as e:
        print(f"失敗: {e}")
        return

    # 3. 驗證
    print("\n驗證：")
    resp = db.from_("lawyers").select("name, email, role, auth_user_id").eq("email", ADMIN_EMAIL).execute()
    if resp.data:
        lawyer = resp.data[0]
        print(f"  姓名：{lawyer['name']}")
        print(f"  Email：{lawyer['email']}")
        print(f"  角色：{lawyer['role']}")
        print(f"  Auth UID：{lawyer['auth_user_id']}")
        print("\n設定完成！可以用此帳號登入儀表板了。")
    else:
        print("  找不到律師資料")


if __name__ == "__main__":
    main()
