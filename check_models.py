from google import genai
import os

# ==========================================
# 你的 API Key
# ==========================================
MY_API_KEY = "AIzaSyBcgO5T36isJ-mBvGmDhuCtXZyHOLtUHqk"

try:
    client = genai.Client(api_key=MY_API_KEY)
    
    print("🔍 正在暴力列出所有模型 (Raw List)...\n")
    
    # 直接印出所有模型物件，不檢查屬性，避免報錯
    for m in client.models.list():
        # 新版 SDK 的模型名稱通常在 m.name 或 m.display_name
        # 我們直接印出 name，這就是我們要填進程式碼的 ID
        print(f"👉 {m.name}")

except Exception as e:
    print(f"\n❌ 查詢失敗：{e}")