# ==========================================
# 區塊 1：匯入模組 (Import Modules)
# ==========================================
# requests: 用來對網站發送請求，像是瀏覽器一樣去「載入」網頁
import requests

# BeautifulSoup: 用來解析 HTML 原始碼，把亂七八糟的網頁代碼變成可以搜尋的物件
from bs4 import BeautifulSoup

# time, random: 用來控制程式暫停的時間，模擬人類行為，避免被網站封鎖
import time
import random

# csv: Python 內建的模組，用來讀寫 CSV 格式的試算表檔案
# import csv

# 把資料丟到資料庫
import pymysql

# ==========================================
# 區塊 2：設定參數
# ==========================================
# 目標網址：巴哈姆特原神板
BASE_URL = "https://forum.gamer.com.tw/B.php?bsn=36730"

# Headers (請求標頭)：
# 這是爬蟲的「偽裝面具」。告訴伺服器我們是 Chrome 瀏覽器，而不是 Python 程式。
# 如果不加這個，很多網站會回傳 403 Forbidden (禁止訪問)。
headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 定義不想抓的關鍵字
BLOCK_KEYWORDS = ["原神版", "兌換碼", "刪除", "序號", "公告"]

DB_SETTINGS = {
    "host": "localhost",
    "user": "root", 
    "password": "password",
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# ==========================================
# 區塊 3：主要爬蟲功能函式
# ==========================================
# 存成 csv 檔案
# def save_to_csv(data_list):
#   filename = "genshin_data.csv"
#   # a 模式 (append) 代表「追加」，這樣可以一邊爬一邊存，不用等全部跑完
#   # utf-8-sig 是為了讓 Excel 中文不亂碼
#   try:
#     with open(filename, 'a', newline='', encoding='utf-8-sig') as f:
#       writer = csv.DictWriter(f, fieldnames=["頁數", "標題", "連結", "內文"])

#       # 如果檔案是空的，先寫入欄位名稱 (Header)
#       if f.tell() == 0:
#         writer.writeheader()
      
#       writer.writerows(data_list)
#       print(f"  └── 成功儲存 {len(data_list)} 筆資料")
#   except Exception as e:
#     print(f"存檔錯誤: {e}")

# 存到資料庫
def save_to_db(data_list):
  try:
    # 1. 建立連線
    connection = pymysql.connect(**DB_SETTINGS)

    with connection.cursor() as cursor:
      # INSERT IGNORE: 如果碰到 url 重複的資料，自動忽略，不要報錯
      sql = """
      insert ignore into bahamut_posts (page_num, title, url, content)
      values (%s, %s, %s, %s)
      """
      # 3. 整理資料 (把 Dict 轉成 Tuple 列表，順序要跟上面的 VALUES 一樣)
      values = []
      for item in data_list:
        values.append((
          item['頁數'],
          item['標題'],
          item['連結'],
          item['內文'],
        ))
      
      # 4. 批量寫入
      if values:
        cursor.executemany(sql, values)
        connection.commit()
        print(f"  └── 成功寫入資料庫: {len(values)} 筆")
      else:
        print("  └── 沒有資料需要寫入")
    
  except Exception as e:
    print(f"資料庫錯誤: {e}")
  finally:
    # 確保連線有關閉
    if "connection" in locals() and connection.open:
      connection.close()

# 抓取內文及回覆
def fetch_content(link):
  try:
    response = requests.get(link, headers=headers)
    if response.status_code == 200:
      soup = BeautifulSoup(response.text, 'html.parser')
      all_bodies_and_reply = soup.select('div.c-post__body, article.reply-content__article')

      collected_texts = []
      for body in all_bodies_and_reply[:15]:
        text = body.get_text(strip=True)
        # 幾個字以上才抓
        if len(text) > 6:
          collected_texts.append(text)

      if collected_texts:
        return "\n\n".join(collected_texts)

  except Exception as e:
    print(f"抓取內文錯誤: {e}")
  return "無有效內容"

# 抓取文章標題 & 連結
def scrape_single_page(page_number):
  target_url = f"{BASE_URL}&page={page_number}"
  print(f"\n=== 正在爬取第 {page_number} 頁: {target_url} ===")
  # 1. 發送 GET 請求
  # requests.get(網址, 標頭) 會回傳一個 Response 物件
  response = requests.get(target_url, headers=headers)
  try:
    # 2. 檢查狀態碼 (Status Code)
    # 200 代表成功，404 代表找不到網頁，500 代表伺服器錯誤
    if response.status_code == 200:
      # 把雜亂的 HTML (response.text) 交給圖書管理員 (soup)
      soup = BeautifulSoup(response.text, 'html.parser')
      # 抓「全部」，包含置頂跟一般
      rows = soup.select("tr.b-list__row")

      print(f"開始爬取...\n")

      # 準備一個 list 來暫存這一批抓到的資料
      batch_data = []

      for row in rows:
        title_div = row.select_one('td.b-list__main')

        if title_div:
          a_tag = title_div.find('a')

          if a_tag:
            title = a_tag.get_text(strip=True)
            raw_link = a_tag['href']
            full_link = "https://forum.gamer.com.tw/" + raw_link

            # 只要標題包含列表中的任何一個詞，就跳過
            if any(keyword in title for keyword in BLOCK_KEYWORDS):
              continue
            
            print(f"[P.{page_number}] 正在分析: {title}")
            # =================================================
            # 把 full_link 丟進去 fetch_content (函式)
            # 然後把結果存到 article_content (新變數)
            # =================================================
            article_content = fetch_content(full_link)

            post_data = {
              "頁數": page_number,
              "標題": title,
              "連結": full_link,
              "內文": article_content,
            }

            batch_data.append(post_data)

            # 記得睡覺，不然會被鎖
            time.sleep(random.uniform(1, 3))

          else:
            print("跳過無連結公告")
      
      if batch_data:
        save_to_db(batch_data)
        print("資料已儲存至資料庫")
      else:
        print("此頁面沒有符合的資料")

    else:
      print(f"連線失敗！狀態碼: {response.status_code}")

  except Exception as e:
    print(f"錯誤訊息: {e}")
  return "無法讀取內容"

if __name__ == "__main__":
  start_page = 1
  end_page = 3
  print(f"開始執行爬蟲，預計從第 {start_page} 頁 爬到 第 {end_page - 1} 頁...")
  for page in range(start_page, end_page):
    scrape_single_page(page)
    
    # 每抓完「一整頁」，稍微休息久一點，模擬人類換頁的動作
    print(f"第 {page} 頁完成，休息 5 秒後繼續...")
    time.sleep(5)
    
  print("\n全部任務完成！")