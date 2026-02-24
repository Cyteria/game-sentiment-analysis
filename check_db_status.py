import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

# 資料庫連線
conn = pymysql.connect(
    host='127.0.0.1',
    user='root',
    password=os.getenv('DB_PASSWORD'),
    db='sentiment_monitor',
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)

with conn.cursor() as cursor:
    # 檢查文章表
    cursor.execute("SELECT count(*) as count FROM bahamut_posts;")
    posts = cursor.fetchone()['count']
    
    # 檢查分析結果表
    cursor.execute("SELECT count(*) as count FROM sentiment_results;")
    results = cursor.fetchone()['count']
    
    # 檢查有沒有「孤兒資料」 (有分析卻找不到文章，或有文章沒分析)
    cursor.execute("""
        SELECT count(*) as count 
        FROM bahamut_posts p 
        JOIN sentiment_results s ON p.uuid = s.post_uuid;
    """)
    joined = cursor.fetchone()['count']

print(f"📊 資料庫健康檢查報告：")
print(f"------------------------")
print(f"1. 原始文章 (bahamut_posts):   {posts} 筆")
print(f"2. 分析結果 (sentiment_results): {results} 筆")
print(f"3. 完整資料 (兩者匹配成功):     {joined} 筆 (Dashboard 只會顯示這個數字)")
print(f"------------------------")

if joined == 0:
    print("❌ 診斷：Dashboard 沒東西是正常的，因為沒有匹配的資料。")
    if posts == 0:
        print("👉 下一步：請執行爬蟲 (crawler.py)")
    elif results == 0:
        print("👉 下一步：請執行分析 (test_analysis.py)")
conn.close()