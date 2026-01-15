import pymysql
from snownlp import SnowNLP
from opencc import OpenCC

# ==========================================
# 設定參數
# ==========================================
DB_SETTINGS = {
    "host": "localhost",
    "user": "root",
    "password": "password", 
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 初始化繁簡轉換器 (t2s = Traditional to Simplified)
cc = OpenCC('t2s')

def analyze_and_update():
  connection = pymysql.connect(**DB_SETTINGS)

  try:
    with connection.cursor() as cursor:
      # 1. 撈取資料：只抓還沒分析過的文章 (WHERE sentiment_score IS NULL)
      # 這樣以後爬蟲抓新文章，這支程式只要跑新的就好，不用全部重算
      print("正在從資料庫讀取未分析的文章...")
      sql_select = "SELECT id, content, title FROM bahamut_posts WHERE sentiment_score IS NULL"
      cursor.execute(sql_select)
      # 把抓到的所有資料拿回來，存在 posts 變數裡 (它是一個 List)
      posts = cursor.fetchall()
      print(f"共有 {len(posts)} 篇文章需要分析。\n")

      # 準備一個空籃子，等等算好的分數都要先暫存在這裡
      updates = []

      # 開始用迴圈，一篇一篇拿出來處理
      for post in posts:
        # 從字典裡取出我們要的資料
        post_id = post['id']
        content = post['content']
        title = post['title']

        # --- AI 分析 (PROCESS) ---
        if not content:
          score = 0.5
        else:
          # 1. 翻譯：把內文從繁體轉成簡體 (提高 AI 辨識率)
          simp_text = cc.convert(content)
          # 2. 建立 SnowNLP 物件：把文字餵給 AI
          s = SnowNLP(simp_text)
          # 3. 取得分數：範圍是 0 (極負面) ~ 1 (極正面)
          score = s.sentiments

          # 把結果打包成一個小組 (分數, ID)，放進籃子裡
          # 順序很重要！因為等一下 SQL update 語法是先填分數，再填 ID
          updates.append((score, post_id))
          
          # 在螢幕上印出來讓我們看進度 (.2f 代表只顯示小數點後兩位)
          print(f"[{score:.2f}] {title[:15]}...")
      
      # --- 步驟 C: 寫回資料庫 (WRITE) ---
      # 如果籃子裡有東西 (updates 不是空的)
      if updates:
        print(f"\n正在將分數寫回資料庫...")

        # 準備更新的 SQL 指令
        # %s 是佔位符，Python 會自動把 updates 裡的資料填進去
        # 語法意思：把某個 ID 的 sentiment_score 修改為某個分數
        sql_update = "UPDATE bahamut_posts SET sentiment_score = %s WHERE id = %s"
        
        # executemany: 批量執行。
        # 它會把 updates 籃子裡的幾百筆資料，一次性地送給資料庫處理 (比跑迴圈快很多)
        cursor.executemany(sql_update, updates)
        
        # 【超級重要】提交變更！
        # 在這裡按下「存檔」鍵。如果沒寫這行，資料庫不會真的改變。
        connection.commit()
        
        print("✅ 完成！資料庫已更新。")
      else:
        print("沒有需要更新的文章。")

  except Exception as e:
    # 如果發生任何錯誤 (例如斷線、SQL寫錯)，會跳到這裡
    print(f"發生錯誤: {e}")

  finally:
    # --- 步驟 D: 清理現場 ---
    # 無論成功或失敗，最後一定要掛斷電話 (關閉連線)
    # 這是為了釋放資源，避免佔用資料庫的連線數
    connection.close()

if __name__ == "__main__":
  analyze_and_update()
