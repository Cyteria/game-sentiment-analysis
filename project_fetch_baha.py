import requests 
import pymysql 
import time 
import os
import random
from bs4 import BeautifulSoup 
from dotenv import load_dotenv 
from urllib.parse import urlparse, parse_qs # 【必要】用來解析網址上的 ID

# 載入環境變數
load_dotenv()
DB_PASSWORD = os.getenv("DB_PASSWORD")

# ==========================================
# 1. 設定區
# ==========================================

TARGET_BOARDS = [
    {"name": "原神", "bsn": "36730"},
    {"name": "鳴潮", "bsn": "74934"}
]

DB_SETTINGS = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": "root", 
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

# 偽裝標頭 (Requests 必須要這個)
HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 18歲驗證 Cookie
COOKIES = {'ckBH_over18': '1'}

BLOCK_KEYWORDS = ["板規", "置頂", "公告", "刪除", "兌換碼", "序號"]

# ==========================================
# 2. 核心功能函式
# ==========================================
def get_latest_post_id(board_name):
  """
  查詢資料庫中該板目前最大的 ID
  """
  connection = None
  try:
    connection = pymysql.connect(**DB_SETTINGS)
    with connection.cursor() as cursor:
      # 使用 CAST 將 id 轉為無符號整數 (UNSIGNED) 來找最大值，避免文字比對錯誤 (例如 "10" < "2")
      sql = "SELECT MAX(CAST(id AS UNSIGNED)) as max_id FROM bahamut_posts WHERE board_name = %s"
      cursor.execute(sql, (board_name,))
      result = cursor.fetchone()
      if result and result['max_id']:
        return int(result['max_id'])
      return 0
  except Exception as e:
    print(f"    ⚠️ 無法取得最新 ID (可能是第一次執行): {e}")
    return 0
  finally:
    if connection and connection.open:
      connection.close()

def save_to_db(data_list):
  """
  將資料寫入 MySQL
  """
  connection = None
  try:
    connection = pymysql.connect(**DB_SETTINGS)
    with connection.cursor() as cursor:
      sql = """
      INSERT IGNORE INTO bahamut_posts 
      (id, board_name, title, content, url, page_num)
      VALUES (%s, %s, %s, %s, %s, %s)
      """
      
      values = []
      for item in data_list:
        values.append((
          item['id'], item['board_name'], item['title'], 
          item['content'], item['url'], item['page_num']
        ))
      
      if values:
        cursor.executemany(sql, values)
        connection.commit()
        print(f"    └── 💾 成功儲存 {len(values)} 筆")
      else:
        print("    └── 無新資料寫入 (重複或空的)")
    
  except Exception as e:
    print(f"    ❌ 資料庫錯誤: {e}")
  finally:
    if connection and connection.open:
      connection.close()

def fetch_content(link):
  """
  抓取內文
  """
  try:
    response = requests.get(link, headers=HEADERS, cookies=COOKIES, timeout=10)
    if response.status_code == 200:
      soup = BeautifulSoup(response.text, 'html.parser')
      
      # 檢查是否被擋
      if "未滿18歲" in soup.get_text(): return None

      main_body = soup.select_one('div.c-post__body, article.reply-content__article')
      if main_body:
        text = main_body.get_text(strip=True, separator=" ")
        if len(text) > 5: return text
  except Exception:
    pass
  return None

# 修改函式定義，多一個 stop_id 參數
def scrape_single_page(board_name, bsn, page_number, stop_id):
  target_url = f"https://forum.gamer.com.tw/B.php?bsn={bsn}&page={page_number}"
  print(f"\n  📄 [{board_name}] 讀取第 {page_number} 頁 (截至 ID: {stop_id})...")
  
  try:
    response = requests.get(target_url, headers=HEADERS, cookies=COOKIES, timeout=10)
    if response.status_code != 200:
      print(f"    ❌ 連線失敗: {response.status_code}")
      return False # 失敗不算停止，回傳 False 繼續嘗試

    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.select("tr.b-list__row")

    if not rows:
        print("    ⚠️ 找不到文章列表")
        return False

    batch_data = []
    should_stop_scraping = False # 標記是否該停止了

    for row in rows:
      # --- [新增] 判斷是否為置頂文 (CSS Class) ---
      # 巴哈的置頂文通常會有 'b-list__row--sticky' 這個 class
      is_sticky_row = 'b-list__row--sticky' in row.get('class', [])

      title_div = row.select_one('td.b-list__main')
      a_tag = title_div.find('a', href=True) if title_div else None
      if not a_tag: continue 

      # 解析 ID (snA)
      try:
          raw_link = a_tag['href']
          full_link = "https://forum.gamer.com.tw/" + raw_link
          parsed_url = urlparse(raw_link)
          query_params = parse_qs(parsed_url.query)
          post_id_str = query_params.get('snA', [None])[0]
          if not post_id_str:
              post_id_str = query_params.get('sn', [None])[0]
          
          if not post_id_str: continue
          current_id = int(post_id_str) # 轉成數字方便比對
      except:
          continue

      # 抓標題
      title_elem = a_tag.select_one(".b-list__main__title")
      title = title_elem.get_text(strip=True) if title_elem else a_tag.get_text(strip=True)

      # 過濾關鍵字 (原本的邏輯)
      if any(k in title for k in BLOCK_KEYWORDS):
        continue
      
      # --- [核心修改] 停止邏輯判斷 ---
      # 規則：
      # 1. 如果不是置頂文 (因為置頂文 ID 可能很舊，我們不能因為它就停)
      # 2. 且 目前文章 ID <= 資料庫最新 ID
      # -> 代表撞到舊牆了，停止！
      if not is_sticky_row and stop_id > 0 and current_id <= stop_id:
          print(f"    🛑 發現舊文章 (ID: {current_id})，觸發停止機制！")
          should_stop_scraping = True
          break # 跳出 row 的迴圈

      # (以下是原本的抓取邏輯)
      print(f"    🔍 抓取: {title[:15]}...", end="")
      content = fetch_content(full_link)
      
      if content:
        print(" ✅")
        batch_data.append({
          "id": current_id, # 這裡可以直接存 int
          "board_name": board_name,
          "title": title,
          "content": content,
          "url": full_link,
          "page_num": page_number
        })
      else:
        print(" ❌ (無內文)")
      
      time.sleep(random.uniform(0.5, 1.0))

    # 儲存本頁資料
    if batch_data:
      save_to_db(batch_data)
    
    # 回傳是否該停止
    return should_stop_scraping

  except Exception as e:
    print(f"    ❌ 頁面錯誤: {e}")
    return False

# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":
  # 設定最大頁數防呆 (例如最多還是只翻 50 頁，以免無限迴圈)
  MAX_PAGES = 50 

  for board in TARGET_BOARDS:
    print(f"\n{'='*40}")
    print(f"🎮 任務啟動：{board['name']} (BSN: {board['bsn']})")
    
    # 1. 先取得該板目前最新的 ID
    latest_id = get_latest_post_id(board['name'])
    print(f"🎯 資料庫目前最新 ID: {latest_id}")
    print(f"{'='*40}")

    for page in range(1, MAX_PAGES + 1):
      # 2. 傳入 latest_id，並接收回傳值
      stop_signal = scrape_single_page(board['name'], board['bsn'], page, latest_id)
      
      if stop_signal:
        print(f"🎉 [{board['name']}] 更新完成！已追上最新進度。")
        break # 跳出頁數迴圈，換下一個看板

      time.sleep(3) 

  print("\n✅ 所有爬蟲任務完成！")