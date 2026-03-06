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

load_dotenv()

# 自動收集所有設定的 API 金鑰
API_KEYS = []
if os.getenv("GROQ_API_KEY"): API_KEYS.append(os.getenv("GROQ_API_KEY"))
if os.getenv("GROQ_API_KEY_2"): API_KEYS.append(os.getenv("GROQ_API_KEY_2"))
if os.getenv("GROQ_API_KEY_3"): API_KEYS.append(os.getenv("GROQ_API_KEY_3"))
if os.getenv("GROQ_API_KEY_4"): API_KEYS.append(os.getenv("GROQ_API_KEY_4"))

DB_PASSWORD = os.getenv("DB_PASSWORD")
if not API_KEYS or not DB_PASSWORD:
    raise ValueError("❌ 錯誤：找不到 API Key 或 DB 密碼！")

# 同時支援判斷 Cloud Run Service (網頁) 與 Cloud Run Job (任務)
IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None or os.getenv('CLOUD_RUN_JOB') is not None
if IS_CLOUD_RUN:
    db_config = {"unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"}
else:
    db_config = {"host": "127.0.0.1", "port": 3306} # 確保本機也是用這個

DB_SETTINGS = {
    "user": "root", "password": DB_PASSWORD, "db": "sentiment_monitor",
    "charset": "utf8mb4", "cursorclass": pymysql.cursors.DictCursor, **db_config
}

MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

# ==========================================
# 2. 工具函式
# ==========================================

def clean_text(text):
    if not text: return ""
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)
    text = re.sub(r'@[\w]+', '', text)
    text = re.sub(r'#B\d+:\d+#', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def deduplicate_reviews(reviews):
    """針對 AI 回傳的列表進行強制去重"""
    if not reviews: return []

    unique_reviews = []
    seen_keys = set()

    for item in reviews:
        key = (
            item.get('main_category'), 
            item.get('sub_category'), 
            item.get('target_character')
        )
        if key not in seen_keys:
            unique_reviews.append(item)
            seen_keys.add(key)
    
    return unique_reviews

def ask_groq_analysis(text):
    prompt = f"""
    你是一個專業的遊戲社群分析師。輸入資料是一串討論串的集合（包含蓋樓者與回覆者）。
    
    【輸入資料】：
    {text}

    【核心指令 1：群體觀點權衡】
    1. **整體情緒優先**：這是一個多人的討論串。請判斷「多數人」的共識。若大多數人認為「簡單/亂殺」，而只有少數人說「難打」，整體分數應偏向正面。
    2. **攻略與心得區分**：若玩家只是在「單純分享隊伍配置/數值」，且語氣中立，請交白卷 `{{"reviews": []}}`。只有當玩家對遊戲機制有明顯的「爽/讚/強/超模」或「爛/燙/難/制裁」等情緒時才進行分析。

    【核心指令 2：嚴禁抄襲範例 (防污染)】
    1. **禁止複製範例字眼**：輸出結果中的 `reason` 與 `keywords` 必須 100% 取自【輸入資料】。若資料中未出現「保底」、「閃退」、「倉庫檢測」等字眼，結果絕對不准出現。
    2. **事實核查**：每一則分析的理由必須註明是誰說的（例：有回覆者提到...）。

    【分類規則 (sub_category 必須使用中文名稱)】:
    1. 機率: 抽卡、掉落率、其他。
    2. 官方: 外掛、福利、其他。
    3. 社交: 公會、其他。
    4. 連線: 平台、連線品質、其他。
    5. 更新: 劇情、玩法 (包含深塔難度、凹關體驗)、活動、地圖、Bug。
    6. 角色: 強度 (超模/弱)、操作 (手法)、立繪、其他。
    7. 媒體: 畫質、音樂、其他。
    8. 金流: 詐騙、其他。

    【輸出規則】:
    1. 分數 -5 到 5。
    2. target_character：若提到特定角色請填入名稱，否則 null。
    3. 嚴格去重：同組合只能輸出一筆。
    4. 只回傳純 JSON。
    """

    # 🔥 優化邏輯：優先嘗試最好的模型，如果所有金鑰都不能跑好模型，才降級
    for model in MODELS:
        for key_index, api_key in enumerate(API_KEYS):
            client = Groq(api_key=api_key)
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一個只會輸出 JSON 的分析 API。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0,
                    response_format={"type": "json_object"}
                )
                return json.loads(completion.choices[0].message.content.strip()), model
            
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "rate limit" in error_msg:
                    print(f"  ⚠️ [Key-{key_index+1}] 額度耗盡，切換下一把金鑰...")
                    continue 
                elif "401" in error_msg or "authentication" in error_msg:
                    print(f"  ❌ [Key-{key_index+1}] 金鑰無效，切換下一把金鑰...")
                    continue
                else:
                    print(f"  ❌ [Key-{key_index+1}] 未知錯誤: {e}，切換下一把...")
                    continue

    print("  ❌❌ 所有 API Key 與模型皆嘗試失敗 (可能全部 Rate Limit)。")
    return None, None

# ==========================================
# 3. 主流程
# ==========================================
def main():
    print(f"🚀 [智慧分析模式] 開始執行 (本次預計處理 {BATCH_SIZE} 筆)...")
    connection = pymysql.connect(**DB_SETTINGS)
    
    try:
        with connection.cursor() as cursor:
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
                print("🎉 目前所有文章都已經是最新的分析狀態！")
                return

            print(f"📋 抓取到 {len(posts)} 筆資料，準備開始分析...")
            
            for i, post in enumerate(posts):
                raw_text = f"遊戲名稱：{post['board_name']}\n文章標題：{post['title']}\n內容：{post['content']}"
                clean_content = clean_text(raw_text)
                
                print(f"[{i+1}/{len(posts)}] {post['title'][:15]}...", end=" ")

                if len(clean_content) < 10:
                    print("⚠️ (字數太少，跳過)")
                    result, model_used = {"reviews": []}, "skipped_too_short"
                    avg_score = 0 
                else:
                    result, model_used = ask_groq_analysis(clean_content[:6000])
                    raw_reviews = result.get('reviews', []) if result else []
                    cleaned_reviews = deduplicate_reviews(raw_reviews)
                    
                    if len(raw_reviews) > len(cleaned_reviews):
                        print(f"(已過濾 {len(raw_reviews) - len(cleaned_reviews)} 筆重複)", end=" ")
                    
                    if result:
                        result['reviews'] = cleaned_reviews

                    if cleaned_reviews:
                        valid_scores = [float(item['sentiment_score']) for item in cleaned_reviews if item.get('sentiment_score') is not None]
                        avg_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0 
                    else:
                        avg_score = 0 

                if result is not None:
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
                    print(f"✅ 完成 (平均分: {avg_score})")
                else:
                    print("\n❌ 所有模型與金鑰皆耗盡，提早中斷本次批次分析！")
                    break

                time.sleep(2)

            print(f"\n✅ 批次處理結束！")

    finally:
        connection.close()

if __name__ == "__main__":
    main()