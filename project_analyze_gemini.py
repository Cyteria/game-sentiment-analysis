import pymysql
import time
import os
import re
from google import genai
from google.genai import types

# ==========================================
# 1. 設定區 (Config)
# ==========================================
API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyBcgO5T36isJ-mBvGmDhuCtXZyHOLtUHqk")

# 資料庫連線設定
DB_SETTINGS = {
    "host": "localhost",
    "user": "root",
    "password": os.getenv("DB_PASSWORD", "password"),
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

MODEL_NAME = "gemini-exp-1206"

# 初始化 Gemini 客戶端
client = genai.Client(api_key=API_KEY)

# ==========================================
# 2. 核心功能：問 AI 給分數
# ==========================================
def ask_gemini_sentiment(text):
    # 提示詞 (Prompt)：教 AI 變成評分機器
    prompt = f"""
    你是一個專業的遊戲輿論分析師。請分析以下這則關於《原神》的玩家留言。
    
    任務目標：請判斷該留言的情緒，並回傳一個 0.0 到 1.0 之間的「浮點數」。
    
    評分標準：
    - 0.0 ~ 0.2: 極度負面 (憤怒、退坑、謾罵、垃圾遊戲)
    - 0.3 ~ 0.4: 輕微負面 (抱怨運氣差、無聊、失望)
    - 0.5: 中立 (純提問、無情緒描述)
    - 0.6 ~ 0.8: 正面 (覺得不錯、有趣、期待)
    - 0.9 ~ 1.0: 極度正面 (神作、推薦、非常喜歡)

    請注意：
    1. 只需要回傳數字 (例如: 0.1 或 0.95)，不要有任何解釋或文字。
    2. 如果無法判斷，請回傳 0.5。
    
    留言內容：
    {text}
    """
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0, # 設為 0 讓答案最精準穩定
            )
        )
        
        # 清理回傳值，只保留數字部分 (避免 AI 回答 "分數是 0.5")
        raw_text = response.text.strip()
        # 用正規表示法抓出數字
        match = re.search(r"(\d+(\.\d+)?)", raw_text)
        if match:
            return float(match.group(1))
        else:
            return 0.5 # 抓不到數字就給中立分
            
    except Exception as e:
        print(f"  ⚠️ Gemini 呼叫失敗: {e}")
        return None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 開始執行輿情分析 (Model: {MODEL_NAME})...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 1. 抓取還沒算過分數 (NULL) 的文章
            # LIMIT 10 是為了先測試，確認沒問題後可以把 LIMIT 拿掉跑全量
            sql_select = "SELECT id, content, title FROM bahamut_posts WHERE sentiment_score IS NULL"
            cursor.execute(sql_select)
            posts = cursor.fetchall()
            
            total_posts = len(posts)
            print(f"📋 預計處理 {total_posts} 篇文章...")
            
            if total_posts == 0:
                print("🎉 所有文章都已經分析完了！(或是資料庫是空的)")
                return

            updates = []
            
            # 2. 逐筆分析
            for i, post in enumerate(posts):
                title = post['title']
                content = post['content']
                # 截斷內容避免 token 爆量 (取前 400 字通常就夠判斷了)
                if len(content) > 400:
                    content = content[:400]
                
                print(f"[{i+1}/{total_posts}] 分析: {title[:15]}...", end=" ")
                
                score = ask_gemini_sentiment(content)
                
                if score is not None:
                    print(f"➔ 🎯 {score}")
                    updates.append((score, post['id']))
                else:
                    print(f"➔ ❌ 失敗")

                # 【重要】免費版 API 限制 (每分鐘 15 次)
                # 為了安全起見，我們每跑一筆休息 5 秒 (這樣一分鐘約 12 筆，絕對安全)
                time.sleep(10)

            # 3. 寫回資料庫
            if updates:
                print(f"💾 正在將 {len(updates)} 筆結果存入資料庫...")
                sql_update = "UPDATE bahamut_posts SET sentiment_score = %s WHERE id = %s"
                cursor.executemany(sql_update, updates)
                connection.commit()
                print("✅ 儲存完成！")
            
    finally:
        connection.close()

if __name__ == "__main__":
    main()