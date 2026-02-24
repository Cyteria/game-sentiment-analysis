import pymysql
import time
import os
import json
import re
from dotenv import load_dotenv
from groq import Groq

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
    db_config = {"unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"}
else:
    db_config = {"host": "localhost"}

DB_SETTINGS = {
    "user": "root", 
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    **db_config
}

# 定義模型
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"  # 新增備援模型

client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. 工具函式
# ==========================================

def clean_text(text):
    """資料清洗：移除網址、ID、樓層標籤、多餘空白"""
    if not text: return ""
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)
    text = re.sub(r'@[\w]+', '', text)
    text = re.sub(r'#B\d+:\d+#', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def ask_groq_analysis(text):
    """
    使用完整版 Prompt 進行詳細情感分析 (含自動備援切換)
    """
    # 注意：f-string 中，JSON 範例的 {} 需要轉義成 {{ }}
    prompt = f"""
    你是一個專業的遊戲評論數據分析師。你的任務是讀取玩家的評論，並根據以下分類規則進行情感分析。

    【輸入資料】：
    {text}

    【分類規則 (詳細定義)】:

    1. 機率 (Probability): 
       - 抽卡(draw): 包含保底、小保底、歪了、雙蛋黃、非酋、歐皇、機率低、卡池毒、坑錢、無課體驗。
       - 掉落率(item_drop): 包含素材掉落、裝備掉落、刷不到、爆率、掉寶率。
       - 升級(item_upgrade): 包含衝裝、強化失敗、爆裝、精煉機率。
       - 其他(other): 無法歸類於上述的機率問題。

    2. 官方 (Official): 
       - 外掛(cheater): 包含腳本、修改器、飛人、作弊、誤鎖帳號、封神榜。
       - 福利(bonus): 包含送石、補償、禮包碼、摳門、大方、營運態度、策劃。
       - 其他(other): 無法歸類於上述的官方問題。

    3. 社交 (Social): 
       - 公會(guild): 包含戰隊、聯盟、俱樂部、公會戰、會長。
       - 其他(other): 包含好友系統、聊天室、世界頻、組隊體驗、玩家互動、社交功能孤兒。

    4. 連線 (Connection): 
       - 平台(platform): 包含閃退、無法登入、手機發燙(如果是因為優化差請歸類在更新-優化)、模擬器、跨平台帳號。
       - 連線品質(quality): 包含延遲、爆Ping、Lag(網路層面)、斷線、伺服器馬鈴薯、排隊、轉圈圈。
       - 其他(other): 無法歸類於上述的連線問題。

    5. 更新 (Update): 
       - 劇情(plot): 包含故事、文案、對話、人設崩壞(劇情向)、結局、吃書。
       - 玩法(htp): 包含遊戲機制、戰鬥系統、作業感重、很肝、每日任務、無聊、耐玩度。
       - 活動(activity): 包含限時活動、聯動、復刻、長草期(無活動)、活動獎勵。
       - 地圖(map): 包含場景設計、探索度、寶箱、空氣牆、跑圖體驗。
       - 優化(optimization): 包含掉幀、卡頓(硬體層面)、耗電、發熱、讀取慢(Loading)。
       - Bug(bug): 包含穿模、卡死、惡性BUG、黑屏、程式錯誤。
       - 新角色(new_char): 包含新角推出速度、限定池、數值膨脹(一代版本一代神)。
       - 其他(other): 無法歸類於上述的更新問題。

    6. 角色 (Character): 
       - 強度(strength): 包含數值、T0/T1、倉管、人權角、做壞了、太弱、退環境、平衡性。
       - 操作(operate): 包含手感、接技、僵直、難度、自動戰鬥AI、笨重。
       - 立繪(vp): 包含審美、美術設計、好不好看、醜、香、婆、老公、皮膚(Skin)、建模精細度、服裝、和諧(被改衣服)。
       - 其他(other): 無法歸類於上述的角色問題。

    7. 媒體 (Media): 
       - 畫質(hp): 包含解析度、畫風、顆粒感、特效華麗度、整體視覺。
       - 音樂(music): 包含BGM、配音(CV)、音效、語音違和感。
       - 其他(other): 無法歸類於上述的媒體問題。

    8. 金流 (Money): 
       - 詐騙(scam): 包含儲值沒收到東西、扣款錯誤、消費糾紛。
       - 其他(other): 包含課金CP值、禮包價格、通行證(Pass)價格、騙課。

    【輸出規則】:
    1. 分數 (sentiment_score) 範圍為 -5 (極度負面) 到 5 (極度正面)。
    2. **【重要】去重與整合規則：針對同一則評論，相同的「主分類」與「子分類」組合只能出現一次。若評論中多次提及同一面向（例如開頭罵抽卡，結尾又罵抽卡），請綜合判斷後「合併」為單一物件回傳，理由 (reason) 需涵蓋整體看法。**
    3. 【嚴格限制】 sub_category 必須完全使用【分類規則】中的「中文名稱」(例如: "抽卡", "外掛", "其他")。絕對禁止使用英文代號或發明新詞。如果找不到合適的，請歸類在該主分類下的 "其他"。
    4. keywords 請回傳一個字串陣列 (Array)，最多 3 個。
    5. 請務必只回傳標準的 JSON 格式，不要包含任何 Markdown 標記 (如 ```json ... ```)。
    6. JSON 格式範例:
    {{
        "reviews": [
            {{
                "main_category": "機率",
                "sub_category": "抽卡",
                "sentiment_score": -4,
                "reason": "整合了玩家對保底機制的不滿以及認為卡池會歪的看法",
                "keywords": ["保底", "歪了", "機率"]
            }},
            {{
                "main_category": "角色",
                "sub_category": "立繪",
                "sentiment_score": -3,
                "reason": "玩家認為這次的新造型設計審美很差，不符合角色設定",
                "keywords": ["審美", "造型", "醜"]
            }}
        ]
    }}
    """

    # 定義一個內部函式來執行 API 呼叫，避免重複程式碼
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
        # 1. 嘗試主力模型
        completion = call_api(PRIMARY_MODEL)
        return json.loads(completion.choices[0].message.content.strip()), PRIMARY_MODEL

    except Exception as e:
        error_msg = str(e)
        # 判斷是否為 Rate Limit (429) 或其他需要切換的情況
        if "429" in error_msg or "Rate limit" in error_msg:
            print(f"  ⚠️ 主模型 ({PRIMARY_MODEL}) 額度耗盡或忙碌，切換至備援模型 ({FALLBACK_MODEL})...")
            try:
                # 2. 嘗試備援模型
                completion = call_api(FALLBACK_MODEL)
                return json.loads(completion.choices[0].message.content.strip()), FALLBACK_MODEL
            except Exception as e2:
                print(f"  ❌ 備援模型也失敗: {e2}")
                return None, None
        else:
            # 如果是其他錯誤 (例如 JSON 解析錯誤，或是 API Key 錯誤)，通常換模型也沒用
            print(f"  ❌ API 呼叫失敗 (主模型): {e}")
            return None, None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 [智慧分析模式] 開始執行 (批次上限 50 筆)...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 🌟【核心修改】SQL 查詢邏輯升級
            # 1. s.post_uuid IS NULL: 代表這篇文章從來沒被分析過
            # 2. p.scraped_at > s.analyzed_at: 代表這篇文章內容更新了 (比上次分析的時間還晚)
            sql = """
            SELECT p.uuid, p.content, p.title, p.board_name 
            FROM bahamut_posts p
            LEFT JOIN sentiment_results s ON p.uuid = s.post_uuid
            WHERE 
                s.post_uuid IS NULL 
                OR 
                p.scraped_at > s.analyzed_at
            LIMIT 50
            """
            cursor.execute(sql)
            posts = cursor.fetchall()
            
            if not posts:
                print("🎉 目前所有文章都已經是最新的分析狀態！")
                return

            print(f"📋 抓取到 {len(posts)} 筆需要處理的文章 (含新文章與內容更新)...")
            
            for i, post in enumerate(posts):
                raw_text = (
                    f"遊戲名稱：{post['board_name']}\n"
                    f"文章標題：{post['title']}\n"
                    f"內容：{post['content']}"
                )
                clean_content = clean_text(raw_text)
                
                print(f"[{i+1}/{len(posts)}] {post['title'][:15]}...", end=" ")

                # 呼叫 AI
                if len(clean_content) < 10:
                    print("⚠️ (字數太少，跳過)")
                    # 空 reviews, 平均分數 0 (中立)
                    result, model_used = {"reviews": []}, "skipped_too_short"
                    avg_score = 0 
                else:
                    # 截斷長度避免爆 Token (可視情況調整)
                    result, model_used = ask_groq_analysis(clean_content[:3500])
                    
                    # 計算平均分數 (總分 / 項目數)
                    reviews = result.get('reviews', []) if result else []
                    if reviews:
                        total_score = sum(item.get('sentiment_score', 0) for item in reviews)
                        avg_score = total_score / len(reviews)
                        avg_score = round(avg_score, 2)
                    else:
                        avg_score = 0 # 沒分析出結果，或內容為中立

                if result is not None:
                    json_str = json.dumps(result, ensure_ascii=False)
                    
                    # 寫入資料庫
                    # 因為我們可能是在更新舊文章的分析，所以 ON DUPLICATE KEY UPDATE 很重要
                    sql_insert = """
                    INSERT INTO sentiment_results 
                    (post_uuid, sentiment_score, analysis_result, model_name, analyzed_at) 
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                        sentiment_score = VALUES(sentiment_score),
                        analysis_result = VALUES(analysis_result),
                        model_name = VALUES(model_name),
                        analyzed_at = VALUES(analyzed_at)
                    """
                    cursor.execute(sql_insert, (post['uuid'], avg_score, json_str, model_used))
                    connection.commit()
                    print(f"✅ 完成 (平均分: {avg_score}, 模型: {model_used})")
                else:
                    print("❌ 失敗")

                # 休息一下，避免對 API 造成太大壓力
                time.sleep(5)

            print("\n✅ 批次處理結束！")

    finally:
        connection.close()

if __name__ == "__main__":
    main()  