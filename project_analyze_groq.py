import pymysql
import time
import os
import json
import re
from dotenv import load_dotenv # 引入讀取套件
from groq import Groq  # 引入 Groq 套件
from utils import clean_text  # 引入清洗工具

# ==========================================
# 1. 設定區
# ==========================================

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# 檢查
if not GROQ_API_KEY or not DB_PASSWORD:
    raise ValueError("❌ 錯誤：找不到環境變數！請檢查 .env 檔案或是系統設定。")

DB_SETTINGS = {
    "host": "localhost",
    "user": "root",
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 使用 Llama 3 70B，它的邏輯能力最強，適合做分類 
MODEL_NAME = "llama-3.3-70b-versatile"

# 初始化 Groq 客戶端
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. 核心：Prompt 工程 (定義八大維度)
# ==========================================
def ask_groq_sentiment(text):
    prompt = f"""
    你是一個專業的遊戲營運分析師。請分析這則玩家留言。

    【分析目標】：
    1. 判斷該留言的情緒分數 (0.0~1.0)。
    2. 判斷該留言提到了哪些「關注維度」，並提取關鍵字。

    【維度定義】：
    - 機率 (機率, 保底, 非酋, 歐皇)
    - 金流 (課金, 禮包, CP值)
    - 官方 (營運, 福利, 外掛, 炎上)
    - 社交 (公會, 好友, 討論區)
    - 連線 (登入, 爆Ping, 跨平台)
    - 更新 (劇情, 玩法, 活動, 地圖, 優化, Bug)
    - 角色 (強度, 操作, 立繪, 聲優)
    - 畫面 (畫質, 特效, 流暢度)

    【輸出格式】：
    請「嚴格」回傳以下 JSON 格式，不要包含 Markdown (```json) 或其他廢話：
    {{
        "score": 0.1,
        "topics": {{
            "更新": ["劇情無聊", "活動太肝"],
            "角色": ["鍾離變強"]
        }}
    }}
    (注意：如果該維度沒提到，就不要列在 topics 裡)

    留言內容：
    {text}
    """

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一個只會輸出 JSON 的分析 API。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,           # 溫度設為 0，讓格式最穩定
            response_format={"type": "json_object"} # 【關鍵】強制 Groq 回傳 JSON 模式
        )
        
        result_text = completion.choices[0].message.content.strip()
        
        # 解析 JSON
        data = json.loads(result_text)
        return data

    except Exception as e:
        print(f"  ⚠️ 分析失敗: {e}")
        return None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 開始執行結構化輿情分析 (Model: {MODEL_NAME})...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 這裡改成：抓取 analysis_result 是 NULL 的文章 (代表還沒做過新版分析)
            # 如果你的資料庫還沒加這個欄位，記得先去 GCP 加！
            sql = "SELECT id, content, title FROM bahamut_posts WHERE analysis_result IS NULL"
            cursor.execute(sql)
            posts = cursor.fetchall()
            
            total = len(posts)
            print(f"📋 還有 {total} 篇文章等待分析...")
            
            updates = []
            
            for i, post in enumerate(posts):
                # 1. 清洗資料
                clean_content = clean_text(post['content'])
                
                # 截斷過長文章 (Llama 3 context 很長，可以給多一點，給 2000 字)
                if len(clean_content) > 2000:
                    clean_content = clean_content[:2000]

                print(f"[{i+1}/{total}] {post['title'][:10]}...", end=" ")
                
                # 2. 呼叫 AI
                result = ask_groq_analysis(clean_content)
                
                if result:
                    # 取得分數與詳細資料
                    score = result.get('score', 0.5)
                    topics = result.get('topics', {})
                    
                    # 把 topics 轉成 JSON 字串存入資料庫
                    json_str = json.dumps(topics, ensure_ascii=False)
                    
                    print(f"➔ 分數:{score} | 維度:{list(topics.keys())}")
                    
                    # 準備更新：同時更新 sentiment_score 和 analysis_result
                    updates.append((score, json_str, post['id']))
                else:
                    print("➔ ❌")

                # 3. 批次存檔
                if len(updates) >= 5:
                    # 更新兩個欄位：sentiment_score (供舊功能用) 和 analysis_result (新功能用)
                    sql_update = "UPDATE bahamut_posts SET sentiment_score = %s, analysis_result = %s WHERE id = %s"
                    cursor.executemany(sql_update, updates)
                    connection.commit()
                    updates = []
                    print("  💾 已存檔")
                
                time.sleep(1) # 稍微休息

            # 存剩下的
            if updates:
                sql_update = "UPDATE bahamut_posts SET sentiment_score = %s, analysis_result = %s WHERE id = %s"
                cursor.executemany(sql_update, updates)
                connection.commit()
                print("✅ 全部完成！")

    finally:
        connection.close()

if __name__ == "__main__":
    main()