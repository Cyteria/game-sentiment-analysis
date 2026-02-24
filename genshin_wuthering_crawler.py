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

# ==========================================
# 1. 環境設定區
# ==========================================
load_dotenv()
DB_PASSWORD = os.getenv("DB_PASSWORD")
IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None

# 資料庫連線設定
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

BLOCK_KEYWORDS = ["版規", "置頂", "公告", "刪除", "兌換", "邀請碼", "序號", "好友", "網頁活動", "互助", "健檢", "隊伍配置", "大佬集中串", "贈送", "祖傳聖遺物", "新手須知"]

MAX_LIST_PAGES = 20   # 測試用 1 頁，正式跑可改回 10 或 20
DAYS_LIMIT = 180     # 只抓半年內的文章

# ==========================================
# 2. 工具函式
# ==========================================

def safe_int(value):
    try:
        if not value: return 0
        cleaned = str(value).strip()
        if cleaned == '-': return 0
        return int(cleaned)
    except (ValueError, TypeError):
        return 0

def clean_text_content(text):
    if not text: return ""
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)
    text = re.sub(r'@[\w]+', '', text)
    text = re.sub(r'#B\d+:\d+#', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def save_to_db(data):
    """
    寫入資料庫 (含內容比對與增量更新邏輯)
    """
    connection = None
    try:
        connection = pymysql.connect(**db_config)
        with connection.cursor() as cursor:
            # 🌟【核心修改】SQL Upsert 邏輯優化
            # 1. 如果 uuid 不存在 -> 執行 INSERT (新文章)
            # 2. 如果 uuid 存在 -> 執行 UPDATE (舊文章)
            # 3. scraped_at 更新邏輯：只有當「內容 (content) 變更」時，才更新 scraped_at
            
            sql = """
            INSERT INTO bahamut_posts (
                uuid, bsn, sna, board_name, title, content, post_url, 
                page_num, content_pages, total_content_pages, 
                created_at, scraped_at, gp_count, bp_count
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, 
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE 
                title = VALUES(title),
                gp_count = VALUES(gp_count),
                bp_count = VALUES(bp_count),
                total_content_pages = VALUES(total_content_pages),
                
                -- 智慧比對：若新抓到的 content 與資料庫不同，更新爬取時間；否則維持原時間
                scraped_at = CASE 
                    WHEN content != VALUES(content) THEN VALUES(scraped_at)
                    ELSE scraped_at 
                END,

                -- 最後才更新 content (必須放在比對之後)
                content = VALUES(content);
            """
            
            cursor.execute(sql, (
                data['uuid'], data['bsn'], data['sna'], data['board_name'], 
                data['title'], data['content'], data['post_url'], 
                data['page_num'], data['content_pages'], data['total_content_pages'], 
                data['created_at'], data['scraped_at'], data['gp_count'], data['bp_count']
            ))
        connection.commit()
    except Exception as e:
        print(f"    ❌ DB寫入失敗: {e}")
    finally:
        if connection and connection.open:
            connection.close()

# ==========================================
# 3. 核心爬蟲邏輯
# ==========================================

def crawl_article_pages(base_meta, list_page_num):
    parsed = urlparse(base_meta['url'])
    query_params = parse_qs(parsed.query)
    
    current_floor_page = 1
    total_content_pages_val = 1 
    
    # 宣告變數來記住這篇文章的發文時間
    thread_created_at = None

    while current_floor_page <= total_content_pages_val:
        print(f"    👉 正在抓取內文第 {current_floor_page} 頁...", end='', flush=True)

        query_params['page'] = [current_floor_page]
        new_query = urlencode(query_params, doseq=True)
        current_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(current_url, headers=HEADERS, cookies=COOKIES, timeout=10)
                if response.status_code != 200:
                    time.sleep(2)
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # --- 日期處理 ---
                if current_floor_page == 1:
                    first_section = soup.select_one('section.c-section')
                    if first_section:
                        mtime_tag = first_section.select_one('.tippy-post-info')
                        if mtime_tag: 
                            thread_created_at = mtime_tag.get('data-mtime')
                
                final_created_at = thread_created_at if thread_created_at else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # 檢查文章是否過期 (只在第1頁檢查)
                if current_floor_page == 1 and thread_created_at:
                    try:
                        post_date = datetime.datetime.strptime(thread_created_at, '%Y-%m-%d %H:%M:%S')
                        if post_date < datetime.datetime.now() - timedelta(days=DAYS_LIMIT):
                            print(f" 👋 文章過期 ({thread_created_at})，跳過。")
                            return 
                    except:
                        pass

                # --- 總頁數更新 ---
                pagination_links = soup.select('.BH-pagebtnA a')
                if pagination_links:
                    page_numbers = []
                    for link in pagination_links:
                        val = safe_int(link.text)
                        if val > 0: page_numbers.append(val)
                    if page_numbers:
                        total_content_pages_val = max(page_numbers)

                # --- 內文抓取 ---
                all_text_blocks = soup.select('.c-article__content, .reply-content__article .comment_content')
                content_list = []
                for block in all_text_blocks:
                    for gamercard in block.select('.article_gamercard'):
                        gamercard.decompose()
                    content_list.append(block.text.strip())
                
                full_content = "\n\n".join(content_list)
                full_content = clean_text_content(full_content)

                if len(full_content) < 10:
                    print(f" [⚠️ 內容過短，跳過]")
                    break

                # --- 數值抓取 ---
                gp_count, bp_count = 0, 0
                if current_floor_page == 1:
                    first_section = soup.select_one('section.c-section')
                    if first_section:
                        gp_tag = first_section.select_one('.gp a.count')
                        bp_tag = first_section.select_one('.bp a.count')
                        if gp_tag: gp_count = safe_int(gp_tag.text)
                        if bp_tag: bp_count = safe_int(bp_tag.text)

                # 固定 UUID 生成邏輯 (BSN + SNA + 頁數)
                unique_key_str = f"{base_meta['bsn']}_{base_meta['sna']}_{current_floor_page}"
                fixed_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, unique_key_str))

                post_data = {
                    "uuid": fixed_uuid,
                    "bsn": base_meta['bsn'],
                    "sna": base_meta['sna'],
                    "board_name": base_meta['board_name'],
                    "title": base_meta['title'],
                    "content": full_content,
                    "post_url": current_url,
                    "page_num": list_page_num,
                    "content_pages": current_floor_page,
                    "total_content_pages": total_content_pages_val,
                    "created_at": final_created_at,
                    "scraped_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "gp_count": gp_count,
                    "bp_count": bp_count
                }

                save_to_db(post_data)
                print(" [完成]")
                time.sleep(random.uniform(1, 2))
                break 

            except Exception as e:
                print(f" [錯誤: {e}]")
                time.sleep(2)
        
        current_floor_page += 1

def boards_crawler(board_name, bsn, list_page):
    target_url = f"https://forum.gamer.com.tw/B.php?bsn={bsn}&page={list_page}"
    print(f"[{board_name}] 正在讀取列表第 {list_page} 頁...")

    try:
        response = requests.get(target_url, headers=HEADERS, cookies=COOKIES, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('tr.b-list__row')

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
            
            # 標題防呆過濾
            if not title or title == "標題" or len(title) < 2:
                continue

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

    except Exception as e:
        print(f"列表頁錯誤: {e}")

if __name__ == "__main__":
    for board in TARGET_BOARDS:
        for page in range(1, MAX_LIST_PAGES + 1):
            boards_crawler(board["name"], board['bsn'], page)
            time.sleep(3)
    print("\n✅ 所有爬蟲任務已完成！")