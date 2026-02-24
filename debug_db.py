import pymysql
import os
import pandas as pd
from dotenv import load_dotenv

# 1. 設定環境
load_dotenv()
print("🚀 開始資料庫診斷...")

try:
    conn = pymysql.connect(
        host='127.0.0.1',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        db='sentiment_monitor',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    print("✅ 資料庫連線成功")
except Exception as e:
    print(f"❌ 資料庫連線失敗: {e}")
    exit()

with conn.cursor() as cursor:
    # 2. 檢查各別資料表筆數
    cursor.execute("SELECT count(*) as c FROM bahamut_posts")
    posts_count = cursor.fetchone()['c']
    
    cursor.execute("SELECT count(*) as c FROM sentiment_results")
    results_count = cursor.fetchone()['c']
    
    print(f"📊 [統計] 文章表 (bahamut_posts): {posts_count} 筆")
    print(f"📊 [統計] 分析表 (sentiment_results): {results_count} 筆")

    # 3. 檢查 JOIN (這是最關鍵的一步！)
    sql_join = """
    SELECT p.title, p.created_at, s.sentiment_score
    FROM bahamut_posts p
    JOIN sentiment_results s ON p.uuid = s.post_uuid
    LIMIT 5
    """
    cursor.execute(sql_join)
    joined_data = cursor.fetchall()
    
    print(f"🔗 [JOIN 測試] 成功對應到的筆數 (預覽前 5 筆): {len(joined_data)}")

    if not joined_data:
        print("❌ 嚴重問題：JOIN 結果為空！這代表文章的 UUID 和分析結果的 UUID 對不起來。")
        print("💡 可能原因：你清空了文章表，但留下了舊的分析結果；或是爬蟲產生了新的 UUID，但分析表還在用舊的。")
    else:
        print("✅ JOIN 成功，資料有對上。現在檢查資料格式...")
        
        # 4. 檢查 Pandas 轉換是否會失敗
        df = pd.DataFrame(joined_data)
        print("\n🧐 [原始資料樣本]")
        print(df)
        
        print("\n🧪 [Pandas 轉換測試]")
        # 測試時間轉換
        df['created_at_fixed'] = pd.to_datetime(df['created_at'], errors='coerce')
        invalid_dates = df['created_at_fixed'].isna().sum()
        
        # 測試分數轉換
        df['score_fixed'] = pd.to_numeric(df['sentiment_score'], errors='coerce')
        invalid_scores = df['score_fixed'].isna().sum()
        
        print(f"❌ 時間轉換失敗 (變成 NaT) 的筆數: {invalid_dates}")
        if invalid_dates > 0:
            print(f"   👉 原始時間格式長這樣: '{df['created_at'].iloc[0]}' (類型: {type(df['created_at'].iloc[0])})")
            
        print(f"❌ 分數轉換失敗 (變成 NaN) 的筆數: {invalid_scores}")

conn.close()