import streamlit as st
import pymysql
import pandas as pd
import os
import time
from dotenv import load_dotenv

# ==========================================
# 1. 設定與連線
# ==========================================
load_dotenv()

st.set_page_config(
    page_title="遊戲輿情分析戰情室",
    page_icon="🎮",
    layout="wide"
)

# 關閉快取，確保除錯時看到最新資料
# @st.cache_data(ttl=60) 
def get_data():
    try:
        conn = pymysql.connect(
            host='127.0.0.1',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            db='sentiment_monitor',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        # 抓取文章與分析結果
        sql = """
        SELECT 
            p.board_name, 
            p.title, 
            p.content,
            p.created_at, 
            p.gp_count, 
            p.bp_count,
            s.sentiment_score, 
            s.analysis_result,
            s.model_name
        FROM bahamut_posts p
        JOIN sentiment_results s ON p.uuid = s.post_uuid
        ORDER BY p.created_at DESC
        """
        
        # 🔥【修改重點】不使用 pd.read_sql，改用最穩定的 cursor 抓取 🔥
        with conn.cursor() as cursor:
            cursor.execute(sql)
            result = cursor.fetchall()
            
        conn.close()
        
        # 直接把 List[Dict] 轉成 DataFrame，這招保證不會錯
        if result:
            return pd.DataFrame(result)
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 資料處理
# ==========================================
raw_df = get_data()

st.title("🎮 遊戲輿情分析戰情室")
st.markdown("監控巴哈姆特熱門遊戲板的情緒趨勢與關鍵議題")

# 🔍【除錯專區】如果還是沒資料，這裡會告訴我們發生什麼事
if raw_df.empty:
    st.warning("⚠️ 警告：資料庫連線成功，但沒有抓到任何資料 (JOIN 結果為 0)。")
    st.info("請檢查：1. 爬蟲有跑嗎？ 2. 分析程式有跑嗎？ 3. 是否清空過資料庫但沒重跑？")
    st.stop()
else:
    # 偷偷顯示一下抓到了幾筆，讓你知道它活著
    st.toast(f"✅ 成功載入 {len(raw_df)} 筆分析資料", icon="🚀")

# --- 資料清洗與轉型 ---
# 1. 強制轉分數為數字
raw_df['sentiment_score'] = pd.to_numeric(raw_df['sentiment_score'], errors='coerce')
# 2. 強制轉時間格式
raw_df['created_at'] = pd.to_datetime(raw_df['created_at'], errors='coerce')

# 3. 移除壞掉的資料
df = raw_df.dropna(subset=['sentiment_score', 'created_at']).copy()

# 再次檢查清洗後是否還有資料
if df.empty:
    st.error("❌ 嚴重錯誤：資料抓到了，但格式全部錯誤，被清洗光了！")
    st.write("原始資料預覽：", raw_df.head())
    st.stop()

# ==========================================
# 3. 側邊欄過濾器 (Sidebar Filter)
# ==========================================
st.sidebar.header("🔍 篩選條件")

# 遊戲看板選擇
all_boards = df['board_name'].unique().tolist()
selected_board = st.sidebar.selectbox("選擇遊戲看板", ["全部"] + all_boards)

# 過濾資料
if selected_board != "全部":
    filtered_df = df[df['board_name'] == selected_board]
else:
    filtered_df = df

# ==========================================
# 4. 關鍵指標 (KPIs)
# ==========================================
col1, col2, col3, col4 = st.columns(4)

total_posts = len(filtered_df)

if not filtered_df.empty:
    avg_score = filtered_df['sentiment_score'].mean()
    positive_ratio = (filtered_df['sentiment_score'] > 0).mean() * 100
    
    max_date = filtered_df['created_at'].max()
    if pd.notna(max_date):
        latest_update = max_date.strftime('%Y-%m-%d %H:%M')
    else:
        latest_update = "N/A"
else:
    avg_score = 0.0
    positive_ratio = 0.0
    latest_update = "N/A"

with col1:
    st.metric("分析文章總數", f"{total_posts} 篇")
with col2:
    delta_color = "normal"
    if avg_score > 1: delta_color = "normal"
    elif avg_score < -1: delta_color = "inverse"
    st.metric("平均情緒指數", f"{avg_score:.2f}", delta_color=delta_color)
with col3:
    st.metric("正面評價佔比", f"{positive_ratio:.1f}%")
with col4:
    st.metric("最後更新時間", latest_update)

st.divider()

# ==========================================
# 5. 圖表視覺化
# ==========================================
col_chart1, col_chart2 = st.columns([2, 1])

with col_chart1:
    st.subheader("📈 情緒趨勢變化 (日均)")
    if not filtered_df.empty:
        daily_trend = filtered_df.groupby(filtered_df['created_at'].dt.date)['sentiment_score'].mean()
        st.line_chart(daily_trend)
    else:
        st.info("無資料可顯示趨勢圖")

with col_chart2:
    st.subheader("📊 情緒分佈")
    if not filtered_df.empty:
        def categorize_score(score):
            if score > 1: return "正面 (>1)"
            if score < -1: return "負面 (<-1)"
            return "中立 (-1~1)"
        
        dist_df = filtered_df['sentiment_score'].apply(categorize_score).value_counts()
        st.bar_chart(dist_df)
    else:
        st.info("無資料可顯示分佈圖")

# ==========================================
# 6. 詳細文章列表
# ==========================================
st.subheader("📋 最新分析文章")

if not filtered_df.empty:
    display_cols = ['created_at', 'board_name', 'title', 'sentiment_score', 'gp_count']
    st.dataframe(
        filtered_df[display_cols].style.background_gradient(subset=['sentiment_score'], cmap='RdYlGn', vmin=-5, vmax=5),
        use_container_width=True,
        column_config={
            "created_at": "發文時間",
            "board_name": "看板",
            "title": "標題",
            "sentiment_score": "情緒分",
            "gp_count": "推文數"
        }
    )
else:
    st.write("目前沒有符合條件的文章。")

# ==========================================
# 7. 原始資料 (隱藏)
# ==========================================
with st.expander("🔍 查看原始資料"):
    if not filtered_df.empty:
        st.write(filtered_df[['title', 'analysis_result', 'model_name']])
    else:
        st.write("無資料")