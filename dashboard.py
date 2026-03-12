import streamlit as st
import pymysql
import pandas as pd
import os
import json
import re
from collections import Counter
from dotenv import load_dotenv
import altair as alt

# ==========================================
# 1. 設定與連線
# ==========================================
load_dotenv()

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

st.set_page_config(page_title="遊戲輿情分析戰情室", page_icon="🎮", layout="wide")

# ==========================================
# 2. 資料獲取與預處理
# ==========================================
@st.cache_data(ttl=300) # 加入快取，每 5 分鐘重抓一次，提升網頁載入速度
def get_data():
    try:
        conn = pymysql.connect(**db_config)
        sql = """
        SELECT p.uuid, p.board_name, p.title, p.content, p.post_url, p.created_at, 
               p.gp_count, p.bp_count, s.sentiment_score, s.analysis_result
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
        return pd.DataFrame()

raw_df = get_data()

st.title("🎮 巴哈姆特遊戲輿情分析室")

if raw_df.empty:
    st.warning("⚠️ 目前資料庫中沒有分析資料。請確認爬蟲與 AI 分析任務是否已執行。")
    st.stop()

raw_df['sentiment_score'] = pd.to_numeric(raw_df['sentiment_score'], errors='coerce')
raw_df['created_at'] = pd.to_datetime(raw_df['created_at'], errors='coerce')
df = raw_df.dropna(subset=['sentiment_score', 'created_at']).copy()
df['date'] = df['created_at'].dt.date

def parse_json(x):
    try: return json.loads(x)
    except: return {}
df['parsed_result'] = df['analysis_result'].apply(parse_json)

# ==========================================
# 3. 側邊欄進階過濾器
# ==========================================
st.sidebar.header("🔍 篩選條件 (Filters)")

all_boards = df['board_name'].unique().tolist()
selected_board = st.sidebar.selectbox("選擇遊戲看板", ["全部"] + all_boards)

min_date = df['date'].min()
max_date = df['date'].max()
if min_date == max_date: max_date = min_date + pd.Timedelta(days=1)
date_range = st.sidebar.date_input("日期範圍", [min_date, max_date], min_value=min_date, max_value=max_date)

sentiment_range = st.sidebar.slider("情緒分數過濾", -5.0, 5.0, (-5.0, 5.0), 0.5)
search_keyword = st.sidebar.text_input("關鍵字搜尋", placeholder="例如：卡頓、福利...")

# 套用過濾
filtered_df = df.copy()
if selected_board != "全部": 
    filtered_df = filtered_df[filtered_df['board_name'] == selected_board]
if len(date_range) == 2: 
    filtered_df = filtered_df[(filtered_df['date'] >= date_range[0]) & (filtered_df['date'] <= date_range[1])]
filtered_df = filtered_df[(filtered_df['sentiment_score'] >= sentiment_range[0]) & (filtered_df['sentiment_score'] <= sentiment_range[1])]
if search_keyword:
    mask = (filtered_df['title'].str.contains(search_keyword, case=False, na=False) | filtered_df['content'].str.contains(search_keyword, case=False, na=False))
    filtered_df = filtered_df[mask]

# ==========================================
# 特徵萃取 (一次性迴圈，提升效能)
# ==========================================
all_keywords = []
all_characters = []
topic_data = []

if not filtered_df.empty:
    for _, row in filtered_df.iterrows():
        res = row['parsed_result']
        if res and 'reviews' in res:
            for review in res['reviews']:
                # 收集關鍵字
                kws = review.get('keywords', [])
                if isinstance(kws, str): kws = re.split(r'[、,，\s]+', kws)
                all_keywords.extend([k for k in kws if len(k.strip()) > 1])
                
                # 收集角色好感度
                target_char = review.get('target_character')
                sentiment = float(review.get('sentiment_score', 0))
                if target_char and str(target_char).strip().lower() not in ['null', 'none', '']:
                    all_characters.append({"character": str(target_char).strip(), "sentiment": sentiment})
                
                # 收集議題分類
                topic_data.append(review.get('main_category', '其他'))

stop_words = {"，", "。", "！", "？", "、", " ", "", "遊戲", "玩家", "一個", "這個", "正面", "負面",}
clean_keywords = [kw for kw in all_keywords if kw not in stop_words]
keyword_counts = Counter(clean_keywords).most_common(50)

# ==========================================
# 4. 關鍵指標 KPIs
# ==========================================
col1, col2, col3 = st.columns(3)
total_posts = len(filtered_df)

if total_posts > 0:
    avg_score = filtered_df['sentiment_score'].mean()
    top_keyword = f"#{keyword_counts[0][0]}" if keyword_counts else "無"
    kw_count = keyword_counts[0][1] if keyword_counts else 0
else:
    avg_score = 0.0; top_keyword = "無"; kw_count = 0

with col1:
    st.metric("文章總數 (Total Posts)", f"{total_posts} 篇")
with col2:
    delta_color = "normal" if avg_score >= 0 else "inverse"
    st.metric("平均情緒指數 (Avg Sentiment)", f"{avg_score:.2f}", delta=f"{avg_score:.2f}", delta_color=delta_color)
with col3:
    st.metric("熱門關鍵字 (Top Trend)", top_keyword, f"提及 {kw_count} 次", delta_color="off")

st.divider()

if filtered_df.empty:
    st.info("目前的篩選條件下沒有符合的文章，請調整左側的過濾條件。")
    st.stop()

# ==========================================
# 5. 戰情室展示 (1)：輿情聲量與情緒雙軸圖
# ==========================================
st.subheader("📊 戰情室展示 (1)：總覽與趨勢追蹤")
daily_trend = filtered_df.groupby('date').agg(
    文章量=('uuid', 'count'), 平均情緒=('sentiment_score', 'mean')
).reset_index()

base = alt.Chart(daily_trend).encode(x=alt.X('date:T', title='日期'))

bar = base.mark_bar(opacity=0.4, color='#6baed6', size=30).encode(
    y=alt.Y('文章量:Q', title='文章聲量 (Volume)', axis=alt.Axis(titleColor='#6baed6'))
)

line = base.mark_line(color='#d62728', strokeWidth=3, point=alt.OverlayMarkDef(size=100, color='#d62728')).encode(
    y=alt.Y('平均情緒:Q', title='情緒分數 (Score)', scale=alt.Scale(domain=[-5, 5]), axis=alt.Axis(titleColor='#d62728')),
    tooltip=['date:T', '文章量:Q', alt.Tooltip('平均情緒:Q', format='.2f')]
)

combo_chart = alt.layer(bar, line).resolve_scale(y='independent').properties(height=400)
st.altair_chart(combo_chart, use_container_width=True)

st.divider()

# ==========================================
# 6. 戰情室展示 (2)：角色排行與熱門字雲
# ==========================================
st.subheader("🧬 戰情室展示 (2)：角色與議題下鑽")
col_s1, col_s2 = st.columns([1, 1])

with col_s1:
    st.write("**🏆 熱門角色好感度排行**")
    if all_characters:
        char_df = pd.DataFrame(all_characters)
        char_stats = char_df.groupby('character').agg(
            討論次數=('character', 'count'), 
            平均好感度=('sentiment', 'mean')
        ).reset_index()
        char_stats = char_stats.sort_values(by='討論次數', ascending=False).head(5)
        
        char_chart = alt.Chart(char_stats).mark_bar(cornerRadiusEnd=4, height=20).encode(
            x=alt.X('討論次數:Q', title='討論次數', axis=alt.Axis(grid=False)),
            y=alt.Y('character:N', sort='-x', title='', axis=alt.Axis(labelFontWeight='bold')),
            color=alt.Color('平均好感度:Q', scale=alt.Scale(scheme='redyellowgreen', domain=[-5, 5]), title='好感度'),
            tooltip=['character:N', '討論次數:Q', alt.Tooltip('平均好感度:Q', format='.2f')]
        ).properties(height=220)
        st.altair_chart(char_chart, use_container_width=True)
    else:
        st.info("無角色討論資料")

    st.divider()

    st.write("**📊 議題分類佔比 (Topic Share)**")
    if topic_data:
        topic_df = pd.DataFrame(Counter(topic_data).items(), columns=['議題', '數量'])
        donut = alt.Chart(topic_df).mark_arc(innerRadius=60).encode(
            theta=alt.Theta(field="數量", type="quantitative"),
            color=alt.Color(field="議題", type="nominal", scale=alt.Scale(scheme='category20')),
            tooltip=['議題', '數量']
        ).properties(height=250)
        st.altair_chart(donut, use_container_width=True)
    else:
        st.info("無議題分類資料")

with col_s2:
    st.write("**☁️ 熱門關鍵字雲 (Keyword Cloud)**")
    if keyword_counts:
        colors = ['#d62728', '#2ca02c', '#1f77b4', '#ff7f0e', '#9467bd', '#8c564b']
        html_cloud = "<div style='display: flex; flex-wrap: wrap; align-content: flex-start; justify-content: center; padding: 30px; background-color: #f8f9fa; border-radius: 10px; height: 550px;'>"
        
        for i, (word, count) in enumerate(keyword_counts[:30]): 
            size = min(52, max(16, 16 + (count / keyword_counts[0][1]) * 36))
            color = colors[i % len(colors)]
            weight = "bold" if size > 26 else "normal"
            html_cloud += f"<span style='font-size: {size}px; color: {color}; font-weight: {weight}; margin: 8px 15px; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);'>{word}</span>"
            
        html_cloud += "</div>"
        st.markdown(html_cloud, unsafe_allow_html=True)
    else:
        st.info("無關鍵字資料")

st.divider()

# ==========================================
# 7. 戰情室展示 (3)：競品對比分析
# ==========================================
if selected_board == "全部" and len(all_boards) > 1:
    st.subheader("⚔️ 戰情室展示 (3)：競品對比分析")
    
    st.write("**跨遊戲聲量趨勢 (Volume Comparison)**")
    comp_daily = filtered_df.groupby(['date', 'board_name']).size().reset_index(name='文章量')
    
    comp_line = alt.Chart(comp_daily).mark_line(point=True, strokeWidth=3).encode(
        x=alt.X('date:T', title='日期'),
        y=alt.Y('文章量:Q', title='討論文章數'),
        color=alt.Color('board_name:N', title='遊戲看板', scale=alt.Scale(scheme='set1')),
        tooltip=['date:T', 'board_name:N', '文章量:Q']
    ).properties(height=400).interactive()
    
    st.altair_chart(comp_line, use_container_width=True)
    
    st.info("💡 **AI 商業洞察**：透過上方趨勢圖可觀察特定遊戲的改版日或炎上事件，是否造成同類競品聲量下降，驗證玩家注意力的『資源排擠效應』。")
    st.divider()

# ==========================================
# 8. 單篇深度檢視
# ==========================================
st.subheader("📋 單篇深度檢視 (Deep Dive)")
display_df = filtered_df.reset_index(drop=True)
post_options = display_df.apply(lambda x: f"{x['created_at'].strftime('%m-%d')} | {x['title']} (分: {x['sentiment_score']})", axis=1).tolist()
selected_option = st.selectbox("請選擇文章：", post_options)
selected_index = post_options.index(selected_option)
selected_post = display_df.iloc[selected_index]

with st.container(border=True):
    st.markdown(f"### 📄 {selected_post['title']}")
    st.caption(f"發文時間: {selected_post['created_at']} | 看板: {selected_post['board_name']} | 推: {selected_post['gp_count']}")
    if selected_post.get('post_url'): st.link_button("🔗 前往巴哈姆特閱讀原文", selected_post['post_url'])
    with st.expander("閱讀原始內文"): st.text(selected_post['content'])
    st.divider()
    
    parsed_data = selected_post['parsed_result']
    if parsed_data and 'reviews' in parsed_data:
        st.write("#### 🤖 AI 分析觀點")
        cols = st.columns(2)
        for i, review in enumerate(parsed_data['reviews']):
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
                    
                    raw_kws = review.get('keywords', [])
                    if isinstance(raw_kws, str): raw_kws = re.split(r'[、,，\s]+', raw_kws)
                    clean_kws = []
                    for k in raw_kws:
                        k = str(k).strip(' 、，。！？()（）"\'[]【】') 
                        if len(k) >= 2 and k not in clean_kws: clean_kws.append(k)
                    if clean_kws: st.caption("關鍵字: " + " 、 ".join([f"`{k}`" for k in clean_kws]))
    else:
        st.warning("這篇文章似乎沒有詳細的分析資料")