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

# 檢查
if not GROQ_API_KEY or not DB_PASSWORD:
    raise ValueError("❌ 錯誤：找不到環境變數！請檢查 .env 檔案或是系統設定。")

# 檢查是否在雲端環境 Google Cloud Run 會自動注入 K_SERVICE 這個環境變數，本機沒有
IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None

if IS_CLOUD_RUN:
    # --- 雲端環境 (Cloud Run) ---
    # 使用 Unix Socket 連線 (這是最快且最安全的方式)
    # 注意：這裡不需要 port
    db_config = {
        "unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"
    }
else:
    # --- 本機環境 (Local) ---
    # 使用 TCP 連線 (搭配您開的 Cloud SQL Proxy)
    db_config = {
        "host": "localhost",
    }

# 共用設定
common_settings = {
    "user": "root", 
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 合併設定
DB_SETTINGS = {**common_settings, **db_config}

# 設定兩個模型
PRIMARY_MODEL = "llama-3.3-70b-versatile"  # 主力 
FALLBACK_MODEL = "llama-3.1-8b-instant"    # 備援

# 初始化 Groq 客戶端
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. 核心：Prompt 工程 (含自動降級機制)
# ==========================================
def ask_groq_analysis(text):
    prompt = f"""
    你是一個專業的遊戲營運分析師。請分析這則玩家留言。
    
    【輸入資料】： {text}

    【評分規則】：
    1. 情緒分數 (score) 範圍為 0.0 (極負面) ~ 1.0 (極正面)，0.5 為中立。
    2. ⚠️ 重要：內容太短、看不出情緒、或純詢問問題，務必給 0.5。
    3. 判斷留言提及的維度，並從「原始留言」中提取具體關鍵字。

    【維度定義與參考線索】：
    分析時請務必參考括號內的關鍵字來歸類，但 topics 的 Key 只能是前面的維度名稱：
    - 機率 (關鍵字：機率, 保底, 非酋, 歐皇, 抽卡, 歪了)
    - 金流 (關鍵字：課金, 儲值, 禮包, CP值, 價格)
    - 官方 (關鍵字：營運, 福利, 外掛, 炎上, 補償, 公告)
    - 社交 (關鍵字：公會, 好友, 討論區, 聯機, 組隊)
    - 連線 (關鍵字：登入, 爆Ping, 跨平台, 斷線, 延遲)
    - 更新 (關鍵字：劇情, 玩法, 活動, 地圖, 優化, Bug, 版本)
    - 角色 (關鍵字：強度, 操作, 立繪, 聲優, 技能, 建模)
    - 畫面 (關鍵字：畫質, 特效, 流暢度, 解析度, 幀數)

    【輸出格式規範】：
    1. 必須是純 JSON 格式，嚴禁包含 Markdown 標籤 (如 ```json) 或任何前言後語。
    2. "topics" 的 Key 必須完全符合上述 8 個「維度名稱」。
    3. ⚠️ 嚴禁直接將「參考線索」中的字眼硬塞進結果，必須是「輸入資料」裡實際出現的內容。
    4. 如果某維度未被提及，則該 Key 不得出現。

    【正確輸出範例結構】：
    {{
        "score": 0.5,
        "topics": {{
            "維度A": ["來自留言的具體文字1"],
            "維度B": ["來自留言的具體文字2"]
        }}
    }}

    現在，請處理以下留言內容：
    {text}
    """

    # 定義一個內部函式來呼叫 API，方便重複使用
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

    # 【關鍵修改】自動切換模型邏輯
    try:
        # 1. 嘗試主力模型 (70b)
        completion = call_api(PRIMARY_MODEL)
        result_text = completion.choices[0].message.content.strip()
        return json.loads(result_text)

    except Exception as e:
        error_msg = str(e)
        # 檢查是否為額度限制錯誤 (429 Rate limit)
        if "429" in error_msg or "Rate limit" in error_msg:
            print(f"  ⚠️ 主模型 ({PRIMARY_MODEL}) 額度耗盡，切換至備援模型 ({FALLBACK_MODEL})...")
            try:
                # 2. 嘗試備援模型 (8b)
                completion = call_api(FALLBACK_MODEL)
                result_text = completion.choices[0].message.content.strip()
                return json.loads(result_text)
            except Exception as e2:
                print(f"  ❌ 備援模型也失敗: {e2}")
                return None
        else:
            # 其他錯誤 (如 JSON 解析失敗、網路斷線)
            print(f"  ⚠️ 分析失敗: {e}")
            return None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 開始執行結構化輿情分析 (預設: {PRIMARY_MODEL} / 備援: {FALLBACK_MODEL})...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            sql = "SELECT id, content, title FROM bahamut_posts WHERE analysis_result IS NULL"
            cursor.execute(sql)
            posts = cursor.fetchall()
            
            total = len(posts)
            print(f"📋 還有 {total} 篇文章等待分析...")
            
            updates = []
            
            for i, post in enumerate(posts):
                raw_text = f"標題：{post['title']}\n內容：{post['content']}"
                clean_content = clean_text(raw_text)
                
                # 字數過少處理
                if len(clean_content) < 10:
                    print(f"[{i+1}/{total}] {post['title'][:10]}... ➔ ⚠️ 字數太少，標記略過")
                    updates.append((0.5, "{}", post['id']))
                else:
                    # 截斷過長文章
                    if len(clean_content) > 2000:
                        clean_content = clean_content[:2000]

                    print(f"[{i+1}/{total}] {post['title'][:10]}...", end=" ")
                    
                    # 呼叫 AI (現在會自動切換模型)
                    result = ask_groq_analysis(clean_content)
                    
                    if result:
                        score = result.get('score', 0.5)
                        topics = result.get('topics', {})
                        json_str = json.dumps(topics, ensure_ascii=False)
                        
                        print(f"➔ 分數:{score} | ✅ {json_str}")
                        updates.append((score, json_str, post['id']))
                    else:
                        print("➔ ❌ (API錯誤)")

                # 批次存檔
                if len(updates) >= 5:
                    sql_update = "UPDATE bahamut_posts SET sentiment_score = %s, analysis_result = %s WHERE id = %s"
                    cursor.executemany(sql_update, updates)
                    connection.commit()
                    updates = []
                    print("  💾 已存檔")
                
                # 調整休息時間：改為 3 秒就好，效率較高
                time.sleep(3)

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