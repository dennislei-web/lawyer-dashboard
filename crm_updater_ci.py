"""
喆律法律事務所 - 諮詢資料更新工具（CI/GitHub Actions 無互動版）
從環境變數讀取帳密，自動抓取最近 2 個月並更新 dashboard.html
"""

import requests
from bs4 import BeautifulSoup
import json
import html
import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime
import time
import sys
import os

# ============ 設定區 ============
BASE_URL = "https://crm.lawyer"
DATA_URL = f"{BASE_URL}/dashboard/statistics/consultation_statistics"
EXCEL_FILE = "consultation_all_data.xlsx"
JSON_FILE = "dashboard_data.json"
# ================================

SIGNED_MAP = {
    "initial": "未填寫",
    "unsigned": "未簽約",
    "signed_and_paid_in_full": "已簽約已付清",
    "signed_with_office_installment": "已簽約事務所分期付款",
    "signed_unpaid": "已簽約未付款",
}

HEADERS = [
    "諮詢日期", "案件編號", "接案所", "品牌", "諮詢律師",
    "當事人", "諮詢方式", "服務項目", "簽約狀態",
    "應收金額（案件委任金）", "已收金額（該案已收金額）", "是否列入計算"
]


def find_login_url(session):
    candidates = [
        f"{BASE_URL}/users/sign_in",
        f"{BASE_URL}/login",
        f"{BASE_URL}/sign_in",
    ]
    resp = session.get(DATA_URL, allow_redirects=True)
    if "sign_in" in resp.url or "login" in resp.url:
        return resp.url
    for url in candidates:
        try:
            resp = session.get(url, allow_redirects=False)
            if resp.status_code in [200, 302]:
                return url
        except:
            pass
    return f"{BASE_URL}/users/sign_in"


def login(session, email, password):
    print("正在偵測登入頁面...")
    login_url = find_login_url(session)
    print(f"  登入頁面：{login_url}")

    resp = session.get(login_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    token = None
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta:
        token = meta.get("content")
    if not token:
        hidden = soup.find("input", {"name": "authenticity_token"})
        if hidden:
            token = hidden.get("value")

    login_data = {
        "user[email]": email,
        "user[password]": password,
        "user[remember_me]": "1",
        "commit": "登入",
    }
    if token:
        login_data["authenticity_token"] = token

    resp = session.post(login_url, data=login_data, allow_redirects=True)

    if "sign_in" not in resp.url and "login" not in resp.url:
        print("✅ 登入成功！")
        return True

    login_data_alt = {"email": email, "password": password}
    if token:
        login_data_alt["authenticity_token"] = token
    resp = session.post(login_url, data=login_data_alt, allow_redirects=True)

    if "sign_in" not in resp.url and "login" not in resp.url:
        print("✅ 登入成功！")
        return True

    print("❌ 登入失敗！請確認帳號密碼是否正確。")
    return False
