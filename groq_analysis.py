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
BATCH_SIZE = 100
MAX_INPUT_LENGTH = 6000 

load_dotenv()

# 自動收集所有 API 金鑰
API_KEYS = [os.getenv(f"GROQ_API_KEY{s}") for s in ["", "_2", "_3", "_4"]]
API_KEYS = [k for k in API_KEYS if k]

DB_PASSWORD = os.getenv("DB_PASSWORD")
if not API_KEYS or not DB_PASSWORD:
    raise ValueError("❌ 錯誤：找不到 API Key 或 DB 密碼！")

IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None or os.getenv('CLOUD_RUN_JOB') is not None
if IS_CLOUD_RUN:
    db_config = {"unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"}
else:
    db_config = {"host": "127.0.0.1", "port": 3306}

DB_SETTINGS = {
    "user": "root", "password": DB_PASSWORD, "db": "sentiment_monitor",
    "charset": "utf8mb4", "cursorclass": pymysql.cursors.DictCursor, **db_config
}

MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

# ==========================================
# 2. 工具函式
# ==========================================

def clean_text(text):
    """清理雜訊並採取頭尾保留策略"""
    if not text: return ""
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)
    text = re.sub(r'@[\w]+', '', text)
    text = re.sub(r'#B\d+:\d+#', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    if len(text) > MAX_INPUT_LENGTH:
        half = MAX_INPUT_LENGTH // 2
        text = text[:half] + "\n... (中間內容省略) ...\n" + text[-half:]
    return text

def deduplicate_reviews(reviews):
    if not reviews: return []
    unique_reviews = []
    seen_keys = set()
    for item in reviews:
        # 增加預設值處理，防止 KeyError
        key = (
            item.get('main_category', '其他'), 
            item.get('sub_category', '其他'), 
            item.get('target_character')
        )
        if key not in seen_keys:
            unique_reviews.append(item)
            seen_keys.add(key)
    return unique_reviews

def ask_groq_analysis(text):
    # 使用你最後確認的高強度融合版 Prompt
    prompt = f"""
    你是一個專業的遊戲社群分析師。輸入資料是一串討論串的集合（包含蓋樓者與回覆者）。請根據以下指令進行深度分析。

    【輸入資料】：
    {text}

    【核心指令 1：群體觀點與對象分析】
    1. **整體情緒優先**：請判斷「多數人」的共識。若大多數人認為「簡單/超模」，而僅極少數人說「難打」，整體分數應偏向正面。
    2. **多對象拆分**：若討論串涉及多個不同角色或主題，請務必拆分為多筆物件輸出。
    3. **中立過濾**：若玩家僅為「單純分享數據/攻略」且語氣中立，或僅為無意義之「卡、推、路過」，請輸出空陣列 `{{ "reviews": [] }}`。

    【核心指令 2：語意證據與防污染】
    1. **原文證據 (關鍵)**：reason 必須包含原文引用，格式如：『回覆者提到的「[原文短句]」顯示出...』。
    2. **嚴禁抄襲範例**：reason 與 keywords 必須 100% 取自【輸入資料】。若資料中未出現該字眼，絕對禁止輸出。
    3. **遊戲術語識別**：
       - 正面：歐氣、不歪、超模、T0、神作、佛心、我的超人、很有誠意、還原、滿意。
       - 負面：非酋、保底、吃相難看、割韭菜、逼課、腳寫的、削弱、退坑、炎上、燙手、難打、制裁。

    【分類規則 (sub_category 必須使用中文名稱)】:
    1. 機率: 抽卡、掉落率、其他。 2. 官方: 外掛、福利、其他。 3. 社交: 公會、其他。 4. 連線: 平台、連線品質、其他。
    5. 更新: 劇情、玩法 (包含難度/凹關體驗)、活動、地圖、Bug。 6. 角色: 強度 (超模/弱)、操作 (手法)、立繪、其他。
    7. 媒體: 畫質、音樂、其他。 8. 金流: 詐騙、價格、其他。

    【絕對評分標準 (sentiment_score)】
    - 5 到 1：正面。⚠️強烈警告：只要 reason 出現正面詞彙，分數【絕對禁止為 0】，至少須為 1 以上。
    - 0：絕對中立。
    - -1 到 -5：負面。

    【嚴格輸出格式】
    請直接輸出 JSON 物件，不要加上任何 Markdown 標記 (如 ```json)：
    {{
    "reviews": [
        {{
        "main_category": "角色",
        "sub_category": "強度",
        "target_character": "角色名稱",
        "sentiment_score": 4,
        "reason": "有回覆者提到「這數值簡直腳寫的」，反映出對強度平衡的明顯不滿。",
        "keywords": ["腳寫的", "不滿"]
        }}
    ]
    }}
    """

    for model in MODELS:
        for key_index, api_key in enumerate(API_KEYS):
            client = Groq(api_key=api_key)
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一個只會輸出正確 JSON 的分析 API。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0,
                    response_format={"type": "json_object"}
                )
                
                # 強化：清理潛在的 Markdown 標記並解析
                content = completion.choices[0].message.content.strip()
                content = re.sub(r'^```json\s*|\s*```$', '', content) 
                return json.loads(content), model
            
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "rate limit" in err:
                    continue 
                print(f"  ❌ [Key-{key_index+1}] 錯誤: {e}")
                continue

    return None, None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 [智慧分析模式] 啟動...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
            # 撈取未分析或有更新的文章
            sql = """
            SELECT p.uuid, p.content, p.title, p.board_name, p.scraped_at
            FROM bahamut_posts p
            LEFT JOIN sentiment_results s ON p.uuid = s.post_uuid
            WHERE s.post_uuid IS NULL OR p.scraped_at > s.analyzed_at
            ORDER BY p.created_at DESC
            LIMIT %s
            """
            cursor.execute(sql, (BATCH_SIZE,))
            posts = cursor.fetchall()
            
            if not posts:
                print("🎉 所有文章皆已分析完成！")
                return

            for i, post in enumerate(posts):
                raw_text = f"遊戲：{post['board_name']}\n標題：{post['title']}\n內容：{post['content']}"
                clean_content = clean_text(raw_text)
                
                print(f"[{i+1}/{len(posts)}] {post['title'][:12]}...", end=" ")

                if len(clean_content) < 15:
                    print("⚠️ (太短)")
                    result, model_used, avg_score = {"reviews": []}, "skipped", 0
                else:
                    result, model_used = ask_groq_analysis(clean_content)
                    
                    if result:
                        raw_reviews = result.get('reviews', [])
                        cleaned_reviews = deduplicate_reviews(raw_reviews)
                        result['reviews'] = cleaned_reviews
                        
                        # 強健的平均分計算
                        valid_scores = []
                        for r in cleaned_reviews:
                            try:
                                valid_scores.append(float(r.get('sentiment_score', 0)))
                            except (ValueError, TypeError):
                                continue
                        avg_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0
                    else:
                        print("❌ 失敗 (跳過本筆)")
                        continue

                # 寫入或更新結果
                json_str = json.dumps(result, ensure_ascii=False)
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
                print(f"✅ ({avg_score})")
                
                time.sleep(1.5)

    finally:
        connection.close()
        print(f"\n✅ 處理結束！")

if __name__ == "__main__":
    main()