import requests
import pymysql
from bs4 import BeautifulSoup
import time
import random
import os
import uuid
import datetime
from datetime import timedelta
import re
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# 環境變數
load_dotenv()
DB_PASSWORD = os.getenv("DB_PASSWORD")
IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None

# 資料庫設定
db_config = {
    "user": "root",
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

if IS_CLOUD_RUN:
    db_config["unix_socket"] = "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db"
else:
    db_config["host"] = "127.0.0.1"
    db_config["port"] = 3306

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
COOKIES = {"ckBH_over18": "1"}

TARGET_BOARDS = [
    {"name": "原神", "bsn": "36730"},
    {"name": "鳴潮", "bsn": "74934"}
]

BLOCK_KEYWORDS = ["版規", "置頂", "公告", "刪除", "兌換", "邀請碼", "序號", "好友", "網頁活動", "互助", "健檢", "隊伍配置", "大佬集中串", "贈送"]

# =================設定區=================
MAX_LIST_PAGES = 20   # 列表頁要抓幾頁
DAYS_LIMIT = 180     # 設定半年 (180天) 為期限
# =======================================

def safe_int(value):
    """安全轉換整數，遇到非數字回傳 0"""
    try:
        if not value: return 0
        cleaned = str(value).strip()
        if cleaned == '-': return 0
        return int(cleaned)
    except (ValueError, TypeError):
        return 0

def clean_text_content(text):
    """
    【全方位清洗函式】
    """
    if not text: return ""
    
    # 1. 移除網址 (含標準與缺損)
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)
    
    # 2. 移除社群 ID (@xxx)
    text = re.sub(r'@[\w]+', '', text)
    
    # 3. 【新增】移除樓層引用標籤 (如 #B2:3789633#)
    # 規則：#B + 數字 + : + 數字 + #
    text = re.sub(r'#B\d+:\d+#', '', text)
    
    # 4. 縮減空白
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()

def save_to_db(data):
    """
    寫入資料庫
    """
    connection = None
    try:
        connection = pymysql.connect(**db_config)
        with connection.cursor() as cursor:
            sql = """
            INSERT INTO bahamut_posts 
            (uuid, bsn, sna, board_name, title, content, post_url, 
             page_num, content_pages, total_content_pages, 
             created_at, scraped_at, gp_count, bp_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                title = VALUES(title),
                content = VALUES(content),
                gp_count = VALUES(gp_count),
                bp_count = VALUES(bp_count),
                page_num = VALUES(page_num),
                content_pages = VALUES(content_pages),
                total_content_pages = VALUES(total_content_pages),
                scraped_at = VALUES(scraped_at);
            """
            
            cursor.execute(sql, (
                data['uuid'],
                data['bsn'],
                data['sna'],
                data['board_name'],
                data['title'],
                data['content'],
                data['post_url'],
                data['page_num'],
                data['content_pages'],
                data['total_content_pages'],
                data['created_at'],
                data['scraped_at'],
                data['gp_count'],
                data['bp_count']
            ))
            
        connection.commit()

    except Exception as e:
        print(f"    ❌ DB寫入失敗: {e}")
    finally:
        if connection and connection.open:
            connection.close()

def crawl_article_pages(base_meta, list_page_num):
    parsed = urlparse(base_meta['url'])
    query_params = parse_qs(parsed.query)
    
    current_floor_page = 1
    total_content_pages_val = 1 
    
    while current_floor_page <= total_content_pages_val:
        
        print(f"    👉 正在抓取內文第 {current_floor_page} 頁 (共 {total_content_pages_val} 頁)...", end='', flush=True)

        query_params['page'] = [current_floor_page]
        new_query = urlencode(query_params, doseq=True)
        current_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(current_url, headers=HEADERS, cookies=COOKIES, timeout=10)
                
                if response.status_code != 200:
                    print(f" [狀態碼 {response.status_code}，重試中 ({attempt}/{MAX_RETRIES})]")
                    time.sleep(2)
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # --- 1. 日期檢查 (僅第1頁) ---
                created_at_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if current_floor_page == 1:
                    first_section = soup.select_one('section.c-section')
                    if first_section:
                        mtime_tag = first_section.select_one('.tippy-post-info')
                        if mtime_tag: 
                            created_at_str = mtime_tag.get('data-mtime')
                            try:
                                post_date = datetime.datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
                                half_year_ago = datetime.datetime.now() - timedelta(days=DAYS_LIMIT)
                                if post_date < half_year_ago:
                                    print(f" 👋 文章過期 ({created_at_str})，跳過不抓。")
                                    return 
                            except:
                                pass

                # --- 2. 更新總頁數 ---
                pagination_links = soup.select('.BH-pagebtnA a')
                if pagination_links:
                    page_numbers = []
                    for link in pagination_links:
                        href = link.get('href', '')
                        if 'B.php' in href: continue
                        val = safe_int(link.text)
                        if val == 0 and 'page=' in href:
                            try:
                                parsed_qs = parse_qs(urlparse(href).query)
                                val = int(parsed_qs.get('page', [0])[0])
                            except:
                                val = 0
                        if val > 0: page_numbers.append(val)
                    if page_numbers:
                        total_content_pages_val = max(page_numbers)

                # --- 3. 抓取內文 ---
                # ==========================================
                # 【修改功能】修改 CSS 選擇器，避開 HOT 標籤並精準抓取留言內容
                # ==========================================
                all_text_blocks = soup.select('.c-article__content, .reply-content__article .comment_content')
                
                content_list = []
                for block in all_text_blocks:
                    # 移除名片檔
                    for gamercard in block.select('.article_gamercard'):
                        gamercard.decompose()

                    text = block.text.strip()
                    if text:
                        content_list.append(text)
                
                full_content = "\n\n".join(content_list)
                full_content = clean_text_content(full_content)

                # 檢查內文是否為空
                if not full_content:
                    print(" [⚠️ 內容為空，跳過儲存]")
                    time.sleep(1)
                    break

                # 抓取 GP/BP (僅第1頁)
                gp_count = 0
                bp_count = 0
                if current_floor_page == 1:
                    first_section = soup.select_one('section.c-section')
                    if first_section:
                        gp_tag = first_section.select_one('.gp a.count')
                        bp_tag = first_section.select_one('.bp a.count')
                        if gp_tag: gp_count = safe_int(gp_tag.text)
                        if bp_tag: bp_count = safe_int(bp_tag.text)
                
                post_data = {
                    "uuid": str(uuid.uuid4()),
                    "bsn": base_meta['bsn'],
                    "sna": base_meta['sna'],
                    "board_name": base_meta['board_name'],
                    "title": base_meta['title'],
                    "content": full_content,
                    "post_url": current_url,
                    "page_num": list_page_num,
                    "content_pages": current_floor_page,
                    "total_content_pages": total_content_pages_val,
                    "created_at": created_at_str,
                    "scraped_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "gp_count": gp_count,
                    "bp_count": bp_count
                }

                save_to_db(post_data)
                print(" [完成]")
                time.sleep(random.uniform(0.8, 1.5))
                break 

            except Exception as e:
                print(f" [失敗: {e}，重試中 ({attempt}/{MAX_RETRIES})]")
                time.sleep(3)
        else:
            print(f" ❌ 第 {current_floor_page} 頁宣告放棄，跳過。")
        
        current_floor_page += 1

def boards_crawler(board_name, bsn, list_page):
    target_url = f"https://forum.gamer.com.tw/B.php?bsn={bsn}&page={list_page}"
    print(f"[{board_name}] 正在讀取列表第 {list_page} 頁...")

    try:
        response = requests.get(target_url, headers=HEADERS, cookies=COOKIES, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('tr.b-list__row')

        if not rows:
            print(f"    ⚠️ 第 {list_page} 頁沒有抓到任何文章列表")
            return

        for row in rows:
            if 'b-list__row--sticky' in row.get('class', []): continue
            
            title_div = row.select_one('td.b-list__main')
            if not title_div: continue
            a_tag = title_div.find('a', href=True)
            if not a_tag: continue

            try:
                raw_link = a_tag['href']
                parsed_url = urlparse(raw_link)
                sna = int(parse_qs(parsed_url.query).get('snA', [None])[0])
            except:
                continue

            title = a_tag.select_one('.b-list__main__title').text.strip()
            if any(keyword in title for keyword in BLOCK_KEYWORDS): continue

            full_link = "https://forum.gamer.com.tw/" + raw_link
            
            base_meta = {
                "bsn": int(bsn),
                "sna": sna,
                "board_name": board_name,
                "title": title,
                "url": full_link
            }
            
            print(f"  └── 發現文章: {title[:15]}...")
            
            crawl_article_pages(base_meta, list_page)
            
            time.sleep(1)

    except Exception as e:
        print(f"列表頁錯誤: {e}")

if __name__ == "__main__":
    for board in TARGET_BOARDS:
        print(f"\n{'='*40}")
        print(f"開始任務：{board['name']} (抓取前 {MAX_LIST_PAGES} 頁列表)")
        print(f"{'='*40}")
        
        for page in range(1, MAX_LIST_PAGES + 1):
            boards_crawler(board["name"], board['bsn'], page)
            print(f"💤 列表第 {page} 頁完成，休息 3 秒...")
            time.sleep(3)

    print("\n✅ 所有爬蟲任務已完成！")