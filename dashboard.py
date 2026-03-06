import streamlit as st
import pymysql
import pandas as pd
import os
import json
from collections import Counter
from dotenv import load_dotenv
import altair as alt

# ==========================================
# 1. 設定與連線
# ==========================================
load_dotenv()

# 加入雲端與本機的資料庫連線自動切換邏輯
IS_CLOUD_RUN = os.getenv('K_SERVICE') is not None or os.getenv('CLOUD_RUN_JOB') is not None
DB_PASSWORD = os.getenv("DB_PASSWORD")

if IS_CLOUD_RUN:
    db_config = {
        "unix_socket": "/cloudsql/games-sentiment-analysis:asia-east1:game-sentiment-db",
        "user": "root",
        "password": DB_PASSWORD,
        "db": "sentiment_monitor",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }
else:
    db_config = {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": DB_PASSWORD,
        "db": "sentiment_monitor",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }

st.set_page_config(
    page_title="遊戲輿情分析戰情室",
    page_icon="🎮",
    layout="wide"
)

# 加入自訂 CSS
st.markdown(
    """
    <style>
    div[data-baseweb="select"] > div {
        background-color: #f0f2f6;
        border: 2px solid #FF4B4B;
        border-radius: 5px;
        color: black;
    }
    div[data-baseweb="popover"] li {
         font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True
)

def get_data():
    try:
        conn = pymysql.connect(**db_config)
        sql = """
        SELECT 
            p.uuid,
            p.board_name, 
            p.title, 
            p.content,
            p.post_url, 
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
        with conn.cursor() as cursor:
            cursor.execute(sql)
            result = cursor.fetchall()
        conn.close()
        return pd.DataFrame(result) if result else pd.DataFrame()
    except Exception as e:
        st.error(f"❌ 資料庫連線失敗: {e}")
        return pd.DataFrame()

# ==========================================
# 2. 資料處理
# ==========================================
raw_df = get_data()

st.title("🎮 巴哈姆特遊戲輿情分析室")

if raw_df.empty:
    st.warning("⚠️ 目前資料庫中沒有分析資料。")
    st.stop()

# --- 資料清洗 ---
raw_df['sentiment_score'] = pd.to_numeric(raw_df['sentiment_score'], errors='coerce')
raw_df['created_at'] = pd.to_datetime(raw_df['created_at'], errors='coerce')
df = raw_df.dropna(subset=['sentiment_score', 'created_at']).copy()

def parse_json(x):
    try:
        return json.loads(x)
    except:
        return {}

df['parsed_result'] = df['analysis_result'].apply(parse_json)

# ==========================================
# 3. 側邊欄過濾器
# ==========================================
st.sidebar.header("🔍 篩選條件")
all_boards = df['board_name'].unique().tolist()
selected_board = st.sidebar.selectbox("選擇遊戲看板", ["全部"] + all_boards)
search_keyword = st.sidebar.text_input("輸入關鍵字搜尋", placeholder="例如：愛彌斯、劇情...")

filtered_df = df.copy()
if selected_board != "全部":
    filtered_df = filtered_df[filtered_df['board_name'] == selected_board]
if search_keyword:
    mask = (filtered_df['title'].str.contains(search_keyword, case=False, na=False) | 
            filtered_df['content'].str.contains(search_keyword, case=False, na=False))
    filtered_df = filtered_df[mask]

# ==========================================
# 4. 關鍵指標 (KPIs)
# ==========================================
col1, col2, col3, col4 = st.columns(4)
total_posts = len(filtered_df)

if not filtered_df.empty:
    avg_score = filtered_df['sentiment_score'].mean()
    positive_ratio = (filtered_df['sentiment_score'] > 0).mean() * 100
    max_date = filtered_df['created_at'].max()
    latest_update = max_date.strftime('%Y-%m-%d %H:%M') if pd.notna(max_date) else "N/A"
else:
    avg_score = 0.0; positive_ratio = 0.0; latest_update = "N/A"

col1.metric("文章篇數", f"{total_posts} 篇")
col2.metric("平均情緒", f"{avg_score:.2f}")
col3.metric("正面佔比", f"{positive_ratio:.1f}%")
col4.metric("最後更新", latest_update)

st.divider()

if not filtered_df.empty:
    # 萃取 AI 分析的細部特徵
    all_categories = []
    all_keywords = []
    all_characters = []

    for _, row in filtered_df.iterrows():
        result = row['parsed_result']
        if result and 'reviews' in result:
            for review in result['reviews']:
                main_cat = review.get('main_category', '其他')
                sub_cat = review.get('sub_category', '其他')
                sentiment = float(review.get('sentiment_score', 0))
                target_char = review.get('target_character')
                
                all_categories.append({
                    "main": main_cat,
                    "sub": sub_cat,
                    "sentiment": sentiment
                })
                all_keywords.extend(review.get('keywords', []))
                
                # 蒐集角色資料 (排除 null 或空值)
                if target_char and str(target_char).strip().lower() not in ['null', 'none', '']:
                    all_characters.append({
                        "character": str(target_char).strip(),
                        "sentiment": sentiment
                    })

    cat_df = pd.DataFrame(all_categories)
    
    # ==========================================
    # 5. 輿情時間趨勢圖
    # ==========================================
    st.subheader("📈 輿情時間趨勢圖")
    trend_df = filtered_df.copy()
    trend_df['date'] = trend_df['created_at'].dt.date
    daily_trend = trend_df.groupby('date').agg(
        文章數=('uuid', 'count'),
        平均情緒=('sentiment_score', 'mean')
    ).reset_index()

    base = alt.Chart(daily_trend).encode(x=alt.X('date:T', title='日期'))
    line = base.mark_line(color='#A9A9A9', strokeDash=[5, 5]).encode(y=alt.Y('平均情緒:Q', title='平均情緒分數', scale=alt.Scale(domain=[-5, 5])))
    points = base.mark_circle().encode(
        y=alt.Y('平均情緒:Q'),
        size=alt.Size('文章數:Q', title='討論熱度 (文章數)', scale=alt.Scale(range=[50, 500])),
        color=alt.Color('平均情緒:Q', scale=alt.Scale(scheme='redyellowgreen', domain=[-5, 5]), legend=None),
        tooltip=['date:T', '文章數:Q', alt.Tooltip('平均情緒:Q', format='.2f')]
    )
    st.altair_chart(line + points, use_container_width=True)

    st.divider()

    # ==========================================
    # 6. 情緒分佈與角色排行
    # ==========================================
    col_s1, col_s2 = st.columns(2)
    
    with col_s1:
        st.subheader("📊 整體情緒分佈")
        def categorize_sentiment(score):
            if score > 0: return '正面 😊'
            elif score < 0: return '負面 😡'
            else: return '中立 😐'
        
        pie_df = filtered_df.copy()
        pie_df['情緒類別'] = pie_df['sentiment_score'].apply(categorize_sentiment)
        pie_counts = pie_df['情緒類別'].value_counts().reset_index()
        pie_counts.columns = ['情緒類別', '文章數']
        
        pie_chart = alt.Chart(pie_counts).mark_arc(innerRadius=60).encode(
            theta=alt.Theta(field="文章數", type="quantitative"),
            color=alt.Color(field="情緒類別", type="nominal", scale=alt.Scale(
                domain=['正面 😊', '中立 😐', '負面 😡'],
                range=['#28a745', '#cccccc', '#dc3545']
            )),
            tooltip=['情緒類別', '文章數']
        )
        st.altair_chart(pie_chart, use_container_width=True)

    with col_s2:
        st.subheader("🏆 熱門角色好感度排行")
        if all_characters:
            char_df = pd.DataFrame(all_characters)
            char_stats = char_df.groupby('character').agg(
                討論次數=('character', 'count'),
                平均好感度=('sentiment', 'mean')
            ).reset_index()
            char_stats = char_stats.sort_values(by='討論次數', ascending=False).head(8)
            
            char_chart = alt.Chart(char_stats).mark_bar().encode(
                x=alt.X('討論次數:Q', title='討論次數'),
                y=alt.Y('character:N', sort='-x', title='角色'),
                color=alt.Color('平均好感度:Q', scale=alt.Scale(scheme='redyellowgreen', domain=[-5, 5]), title='好感度'),
                tooltip=['character:N', '討論次數:Q', alt.Tooltip('平均好感度:Q', format='.2f')]
            )
            st.altair_chart(char_chart, use_container_width=True)
        else:
            st.info("目前的篩選條件下無角色討論資料")

    st.divider()

    # ==========================================
    # 7. 議題分析與關鍵字
    # ==========================================
    col_k1, col_k2 = st.columns(2)

    with col_k1:
        st.subheader("🔥 熱門討論議題 (主次分類下鑽)")
        if not cat_df.empty:
            sub_cats = cat_df.groupby(['main', 'sub']).size().reset_index(name='討論次數')
            top_mains = cat_df['main'].value_counts().head(5).index
            sub_cats_top = sub_cats[sub_cats['main'].isin(top_mains)]
            
            chart = alt.Chart(sub_cats_top).mark_bar().encode(
                x=alt.X('sum(討論次數):Q', title='總討論次數'),
                y=alt.Y('main:N', sort='-x', title='主分類'),
                color=alt.Color('sub:N', title='次分類 (圖例)'),
                tooltip=['main', 'sub', '討論次數']
            )
            st.altair_chart(chart, use_container_width=True)

    with col_k2:
        st.subheader("💬 熱門關鍵字雲")
        if all_keywords:
            stop_words = {"，", "。", "！", "？", "、", "；", "：", "（", "）", " ", "", ",", ".", "(", ")", "!", "?"}
            clean_keywords = [kw for kw in all_keywords if kw not in stop_words and len(kw.strip()) > 1]
            keyword_counts = Counter(clean_keywords).most_common(12)
            
            st.write("玩家最常提到的詞彙：")
            for word, count in keyword_counts:
                # 簡單利用 Markdown 語法調整大小粗細
                size = min(1.5, 0.8 + (count / (len(clean_keywords) or 1)) * 10) 
                st.markdown(f"**{word}** ({count}次)")
        else:
            st.info("無關鍵字資料")

st.divider()

# ==========================================
# 8. 單篇深度檢視
# ==========================================
st.subheader("📋 文章深度檢視")

if not filtered_df.empty:
    display_df = filtered_df.reset_index(drop=True)
    post_options = display_df.apply(
        lambda x: f"{x['created_at'].strftime('%m-%d')} | {x['title']} (分: {x['sentiment_score']})", axis=1
    ).tolist()
    
    selected_option = st.selectbox("請選擇文章：", post_options)
    selected_index = post_options.index(selected_option)
    selected_post = display_df.iloc[selected_index]
    
    with st.container(border=True):
        st.markdown(f"### 📄 {selected_post['title']}")
        st.caption(f"發文時間: {selected_post['created_at']} | 看板: {selected_post['board_name']} | 推: {selected_post['gp_count']}")
        
        post_url = selected_post.get('post_url')
        if post_url:
            st.link_button("🔗 前往巴哈姆特閱讀原文", post_url)

        with st.expander("閱讀原始內文"):
            st.text(selected_post['content'])
        
        st.divider()
        
        parsed_data = selected_post['parsed_result']
        if parsed_data and 'reviews' in parsed_data:
            st.write("#### 🤖 AI 分析觀點")
            reviews = parsed_data['reviews']
            cols = st.columns(2)
            for i, review in enumerate(reviews):
                col = cols[i % 2]
                score = review.get('sentiment_score', 0)
                emoji = "😊" if score > 0 else "😡" if score < 0 else "😐"
                with col:
                    with st.container(border=True):
                        target_char = review.get('target_character')
                        char_tag = f"【{target_char}】" if target_char and str(target_char).lower() != 'null' else ""
                        st.markdown(f"**{emoji} {char_tag}{review.get('main_category')} - {review.get('sub_category')}**")
                        st.markdown(f"分數: `{score}`")
                        st.write(f"💬 {review.get('reason')}")
                        kws = review.get('keywords', [])
                        if kws:
                            st.caption("關鍵字: " + " 、 ".join([f"`{k}`" for k in kws]))
        else:
            st.warning("這篇文章似乎沒有詳細的分析資料")
else:
    st.info("目前沒有文章可供分析")