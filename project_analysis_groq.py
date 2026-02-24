import pymysql
import time
import os
import json
import random
from dotenv import load_dotenv
from groq import Groq
from utils import clean_text 

# ==========================================
# 1. 設定區
# ==========================================

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PASSWORD = os.getenv("DB_PASSWORD")

if not GROQ_API_KEY or not DB_PASSWORD:
    raise ValueError("❌ 錯誤：找不到環境變數！請檢查 .env 檔案或是系統設定。")

IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None

if IS_CLOUD_RUN:
    db_config = {
        "unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"
    }
else:
    db_config = {
        "host": "localhost",
    }

common_settings = {
    "user": "root", 
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

DB_SETTINGS = {**common_settings, **db_config}

PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"

client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. 核心：Prompt 工程
# ==========================================
def ask_groq_analysis(text):
    # 【修改點 1】這裡要回傳 Tuple (結果, 模型名稱)，以便存入資料庫
    prompt = f"""
    你是一個專業的遊戲營運分析師。請分析這則玩家留言。
    
    【輸入資料】：
    {text}

    【評分規則】：
    1. 情緒分數 (score) 範圍為 0.0 (極負面) ~ 1.0 (極正面)，0.5 為中立。
    2. ⚠️ 重要：內容太短、看不出情緒、或純詢問問題，務必給 0.5。
    3. 判斷留言提及的維度，並從「原始留言」中提取具體關鍵字。

    【維度定義與參考線索】：
    - 機率 (關鍵字：機率, 保底, 非酋, 歐皇, 抽卡, 歪了)
    - 金流 (關鍵字：課金, 儲值, 禮包, CP值, 價格)
    - 官方 (關鍵字：營運, 福利, 外掛, 炎上, 補償, 公告)
    - 社交 (關鍵字：公會, 好友, 討論區, 聯機, 組隊)
    - 連線 (關鍵字：登入, 爆Ping, 跨平台, 斷線, 延遲)
    - 更新 (關鍵字：劇情, 玩法, 活動, 地圖, 優化, Bug, 版本)
    - 角色 (關鍵字：強度, 操作, 立繪, 聲優, 技能, 建模)
    - 畫面 (關鍵字：畫質, 特效, 流暢度, 解析度, 幀數)

    【輸出格式規範】：
    1. 必須是純 JSON 格式，嚴禁包含 Markdown 標籤。
    2. "topics" 的 Key 必須完全符合上述 8 個「維度名稱」。
    3. 如果某維度未被提及，則該 Key 不得出現。

    【正確輸出範例結構】：
    {{
        "score": 0.5,
        "topics": {{
            "維度A": ["來自留言的具體文字1"],
            "維度B": ["來自留言的具體文字2"]
        }}
    }}
    """

    def call_api(model_name):
        return client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一個只會輸出 JSON 的分析 API。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

    try:
        completion = call_api(PRIMARY_MODEL)
        # 回傳：(結果JSON, 使用的模型名稱)
        return json.loads(completion.choices[0].message.content.strip()), PRIMARY_MODEL

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Rate limit" in error_msg:
            print(f"  ⚠️ 主模型額度耗盡，切換至備援模型 ({FALLBACK_MODEL})...")
            try:
                completion = call_api(FALLBACK_MODEL)
                return json.loads(completion.choices[0].message.content.strip()), FALLBACK_MODEL
            except Exception as e2:
                print(f"  ❌ 備援模型也失敗: {e2}")
                return None, None
        else:
            print(f"  ⚠️ 分析失敗: {e}")
            return None, None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 開始執行結構化輿情分析 (寫入 sentiment_results 表)...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 【修改點 2】 SQL 改用 JOIN 檢查新表
            # 邏輯：找出 bahamut_posts 有，但 sentiment_results 沒有的 uuid
            sql = """
            SELECT p.uuid, p.content, p.title, p.board_name 
            FROM bahamut_posts p
            LEFT JOIN sentiment_results s ON p.uuid = s.post_uuid
            WHERE s.post_uuid IS NULL
            """
            cursor.execute(sql)
            posts = cursor.fetchall()
            
            total = len(posts)
            print(f"📋 還有 {total} 篇文章等待分析...")
            
            # 用來存批次資料的 list
            batch_data = [] 
            
            for i, post in enumerate(posts):
                raw_text = (
                    f"遊戲名稱：{post['board_name']}\n"
                    f"文章標題：{post['title']}\n"
                    f"內容：{post['content']}"
                )
                
                clean_content = clean_text(raw_text)
                
                # 初始化變數
                score = 0.5
                json_str = "{}"
                model_used = "skipped"

                # 字數檢查
                if len(clean_content) < 10:
                    print(f"[{i+1}/{total}] {post['title'][:10]}... ➔ ⚠️ 字數太少，標記略過")
                    # 【修改點 3】 這裡改用 post['uuid'] 而不是 post['id']
                    batch_data.append((post['uuid'], 0.5, "{}", "skipped_too_short"))
                else:
                    if len(clean_content) > 2500:
                        clean_content = clean_content[:2500]

                    print(f"[{i+1}/{total}] [{post['board_name']}] {post['title'][:10]}...", end=" ")
                    
                    # 呼叫 AI
                    result, model_used = ask_groq_analysis(clean_content)
                    
                    if result:
                        score = result.get('score', 0.5)
                        topics = result.get('topics', {})
                        json_str = json.dumps(topics, ensure_ascii=False)
                        
                        print(f"➔ 分數:{score} | 模型:{model_used} | ✅ OK")
                        # 【修改點 4】 準備寫入資料：(post_uuid, sentiment_score, analysis_result, model_name)
                        batch_data.append((post['uuid'], score, json_str, model_used))
                    else:
                        print("➔ ❌ (API錯誤)")

                # ==========================================
                # 【修改點 5】 批次寫入 sentiment_results 表 (INSERT)
                # ==========================================
                if len(batch_data) >= 5:
                    sql_insert = """
                    INSERT INTO sentiment_results 
                    (post_uuid, sentiment_score, analysis_result, model_name) 
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        sentiment_score = VALUES(sentiment_score),
                        analysis_result = VALUES(analysis_result),
                        model_name = VALUES(model_name),
                        analyzed_at = CURRENT_TIMESTAMP
                    """
                    cursor.executemany(sql_insert, batch_data)
                    connection.commit()
                    batch_data = [] # 清空
                    print("  💾 已寫入新表")
                
                time.sleep(5)

            # 迴圈結束後，處理剩下的
            if batch_data:
                sql_insert = """
                INSERT INTO sentiment_results 
                (post_uuid, sentiment_score, analysis_result, model_name) 
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    sentiment_score = VALUES(sentiment_score),
                    analysis_result = VALUES(analysis_result),
                    model_name = VALUES(model_name),
                    analyzed_at = CURRENT_TIMESTAMP
                """
                cursor.executemany(sql_insert, batch_data)
                connection.commit()
                print("✅ 全部完成！")

    finally:
        connection.close()

if __name__ == "__main__":
    main()