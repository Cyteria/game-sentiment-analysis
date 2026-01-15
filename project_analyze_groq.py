import pymysql
import time
import os
import re
from groq import Groq  # 引入 Groq 套件

# ==========================================
# 1. 設定區
# ==========================================
# 填入你的 Groq API Key
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")

DB_SETTINGS = {
    "host": "localhost",
    "user": "root",
    "password": os.getenv("DB_PASSWORD", "password"),
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 選擇模型：Llama 3.3 70B (準確度高) 或 llama3-8b-8192 (速度極快)
MODEL_NAME = "llama-3.3-70b-versatile"

# 初始化 Groq 客戶端
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. 核心功能：呼叫 Groq (Llama 3)
# ==========================================
def ask_groq_sentiment(text):
    prompt = f"""
    你是一個專業的遊戲輿論分析師。請分析以下這則關於《原神》的玩家留言。
    
    任務：判斷情緒並給予 0.0 (負面) 到 1.0 (正面) 的分數。
    
    標準：
    - 0.0~0.2: 憤怒、退坑、謾罵 (如: 垃圾遊戲、策劃腦癱)
    - 0.3~0.4: 抱怨、失望 (如: 太非了、無聊)
    - 0.5: 中立
    - 0.6~0.8: 正面
    - 0.9~1.0: 極度推薦
    
    【重要】：你只需要回傳一個數字（例如 0.1 或 0.9），不要有任何解釋、不要標點符號、不要寫 "分數："。
    
    留言內容：
    {text}
    """
    
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一個只會輸出數字的情緒分析機器人。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0, # 設為 0 讓結果最穩定
            max_tokens=10  # 我們只需要一個數字，不用浪費 token
        )
        
        # 取得回應文字
        result_text = completion.choices[0].message.content.strip()
        
        # 用正規表示法抓數字 (雙重保險，怕它回傳 "分數是 0.5")
        match = re.search(r"(\d+(\.\d+)?)", result_text)
        if match:
            return float(match.group(1))
        else:
            print(f"  ⚠️ 無法解析回應: {result_text}")
            return 0.5
            
    except Exception as e:
        # 如果遇到 429 (Rate Limit)，Groq 通常會告訴你要等多久
        print(f"  ⚠️ Groq 呼叫失敗: {e}")
        return None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 開始執行 Groq 分析 (Model: {MODEL_NAME})...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 抓取未分析的文章
            sql_select = "SELECT id, content, title FROM bahamut_posts WHERE sentiment_score IS NULL"
            cursor.execute(sql_select)
            posts = cursor.fetchall()
            
            total = len(posts)
            print(f"📋 還有 {total} 篇文章等待分析...")
            
            updates = []
            
            for i, post in enumerate(posts):
                # 截斷內容 (Groq 處理長文很快，但為了省資源還是切一下)
                content = post['content'][:800]
                print(f"[{i+1}/{total}] 分析: {post['title'][:10]}...", end=" ")
                
                score = ask_groq_sentiment(content)
                
                if score is not None:
                    print(f"➔ ⚡ {score}")
                    updates.append((score, post['id']))
                else:
                    print(f"➔ ❌ 失敗")

                # 存檔機制 (每 10 筆存一次)
                if len(updates) >= 10:
                    sql_update = "UPDATE bahamut_posts SET sentiment_score = %s WHERE id = %s"
                    cursor.executemany(sql_update, updates)
                    connection.commit()
                    updates = []
                    print("  💾 (已存檔)")

                # Groq 速度極快，每分鐘允許 30 次請求 (免費版)
                # 我們休息 2 秒就很安全了 (比 Gemini 快很多)
                time.sleep(2)

            # 最後存檔
            if updates:
                sql_update = "UPDATE bahamut_posts SET sentiment_score = %s WHERE id = %s"
                cursor.executemany(sql_update, updates)
                connection.commit()
                print("✅ 全部完成！")
            
    finally:
        connection.close()

if __name__ == "__main__":
    main()