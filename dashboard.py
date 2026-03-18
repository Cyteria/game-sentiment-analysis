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
@st.cache_data(ttl=300) # 每 5 分鐘重抓一次
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

# 新增：為圓餅圖準備的情緒分類標籤
def categorize_sentiment(score):
    if score >= 1: return "正面 (Positive)"
    elif score <= -1: return "負面 (Negative)"
    else: return "中立 (Neutral)"
df['sentiment_category'] = df['sentiment_score'].apply(categorize_sentiment)

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

# ✅ 新增：AI 議題分類篩選 (提取所有可用的主分類)
available_topics = set()
for res in df['parsed_result']:
    if res and isinstance(res, dict) and 'reviews' in res:
        for review in res['reviews']:
            category = review.get('main_category')
            # 確保有值，且字串長度大於 1，才會被加入選單
            if category and len(str(category).strip()) > 1:
                available_topics.add(str(category).strip())

topics_list = ["全部"] + sorted(list(available_topics))
selected_topic = st.sidebar.selectbox("🎯 議題分類篩選 (AI 判讀)", topics_list)

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

# ✅ 新增：套用 AI 議題分類的過濾邏輯
if selected_topic != "全部":
    mask_topic = filtered_df['parsed_result'].apply(
        lambda res: any(r.get('main_category') == selected_topic for r in res.get('reviews', [])) if isinstance(res, dict) else False
    )
    filtered_df = filtered_df[mask_topic]

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
                # 取得原本的關鍵字
                raw_kws = review.get('keywords', [])
                
                # 如果是字串，先進行分割
                if isinstance(raw_kws, str): raw_kws = re.split(r'[、,，\s]+', raw_kws)
                
                # 統一轉換為小寫並去除空白
                normalized_kws = [k.lower().strip() for k in raw_kws]
                
                # 只保留長度大於 1 的乾淨關鍵字
                all_keywords.extend([k for k in normalized_kws if len(k) > 1])
                
                # 定義「非角色」的黑名單
                char_blacklist = ['絕區零', '原神', '鳴潮', '戰雙', '帕彌什ˇ', '崩壞', '遊戲', '官方', '策劃', '客服', '公司', '米哈遊', '庫洛']
                
                target_char = review.get('target_character')
                sentiment = float(review.get('sentiment_score', 0))

                # ✅ 新增：角色別名與同義詞對照表 (Alias Mapping)
                char_aliases = {
                    # ================= 絕區零 (ZZZ) =================
                    "雅": "星見雅",
                    "鯊魚妹": "艾蓮",
                    "鯊魚": "艾蓮",
                    "狼哥": "萊卡恩",
                    "老鼠": "簡",
                    "簡杜": "簡",
                    "狡兔屋老大": "妮可",
                    "社長": "珂蕾妲",
                    "警官": "朱鳶",
                    "朱隊": "朱鳶",
                    "漢堡妹": "安比",
                    "女僕長": "麗娜",
                    "貓又": "貓宮又奈",

                    # ================= 鳴潮 (Wuthering Waves) =================
                    "暗主": "漂泊者",
                    "衍主": "漂泊者",
                    "光主": "漂泊者",
                    "卡子哥": "卡卡羅",
                    "綠龍": "忌炎",
                    "將軍": "忌炎",
                    "牢相": "相里要",
                    "計算機": "相里要",
                    "汐寶": "今汐",
                    "離老師": "長離",
                    "離神": "長離",
                    "吟霖媽媽": "吟霖",
                    "粉毛": "安可",
                    "散華": "散華",
                    "小護士": "維里奈",
                    "烏龜": "淵武",

                    # ================= 原神 (Genshin Impact) =================
                    "萬葉": "楓原萬葉",
                    "葉天帝": "楓原萬葉",
                    "快樂風男": "楓原萬葉",
                    "帝君": "鍾離",
                    "岩王爺": "鍾離",
                    "雷神": "雷電將軍",
                    "影": "雷電將軍",
                    "煮飯婆": "雷電將軍",
                    "水神": "芙寧娜",
                    "芙芙": "芙寧娜",
                    "水龍": "那維萊特",
                    "水龍王": "那維萊特",
                    "龍王": "那維萊特",
                    "那維": "那維萊特",
                    "散兵": "流浪者",
                    "崩帽": "流浪者",
                    "公子": "達達利亞",
                    "達達鴨": "達達利亞",
                    "夜天后": "夜蘭",
                    "堂主": "胡桃",
                    "黃毛": "旅行者",
                    "熒": "旅行者",
                    "空": "旅行者",
                    "凌華": "神里綾華",
                    "神子": "八重神子",

                    # ================= 戰雙帕彌什 (PGR) =================
                    # 戰雙玩家通常以「機體名稱」或「特徵」來稱呼角色
                    "白毛": "露西亞", 
                    "深紅": "露西亞",
                    "深紅之淵": "露西亞",
                    "囚影": "露西亞",
                    "鴉羽": "露西亞",
                    "深痕": "比安卡",
                    "真理": "比安卡",
                    "魔女": "比安卡",
                    "超刻": "里",
                    "亂數": "里",
                    "火神": "里",
                    "極晝": "麗芙",
                    "仰光": "麗芙",
                    "流光": "麗芙",
                    "緋耀": "薇拉",
                    "狗狗": "薇拉",
                    "幻奏": "賽琳娜",
                    "榮光": "庫洛姆",
                    "萬事": "萬事",
                }

                if target_char:
                    char_name = str(target_char).strip()
                    if char_name.lower() not in ['null', 'none', ''] and char_name not in char_blacklist:
                        all_characters.append({"character": char_name, "sentiment": sentiment})
                
                topic_data.append(review.get('main_category', '其他'))

# 擴充了停用詞庫，讓字雲更準確
stop_words = {"，", "。", "！", "？", "、", " ", "", "遊戲", "玩家", "一個", "這個", "正面", "負面", "因為", "所以", "然後", "覺得", "不滿", "腳寫的", "中立", "滿意", "證據"}
clean_keywords = [kw for kw in all_keywords if kw not in stop_words]
keyword_counts = Counter(clean_keywords).most_common(50)

# ==========================================
# 4. 關鍵指標 KPIs 與 炎上預警系統
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

# 🚨 炎上預警系統：根據平均分數動態跳出提示
if total_posts > 0:
    if avg_score <= -3.0:
        board_text = f"【{selected_board}】" if selected_board != "全部" else "整體"
        st.error(f"🚨 **炎上預警**：{board_text}目前篩選範圍內的平均情緒降至 **{avg_score:.2f}**，社群氛圍偏向負面，請密切關注可能引發公關危機的議題！")
    elif avg_score >= 3.0:
        board_text = f"【{selected_board}】" if selected_board != "全部" else "整體"
        st.success(f"🎉 **好評發燒**：{board_text}目前篩選範圍內的平均情緒高達 **{avg_score:.2f}**，玩家反響熱烈，建議可趁勢加大行銷推廣！")
    
    with st.expander("ℹ️ AI 情緒評分標準指南 (Scoring Rubric)"):
        st.markdown("""
        為了確保情緒分數具備客觀的商業參考價值，系統賦予了 LLM 嚴格的評分錨點 (Anchor Points)：
        * **🟢 +4 ~ +5 (極度狂熱/死忠)**：玩家表達強烈喜愛、極力推坑，甚至表示願意為此大量付費（例如：「這神作吧」、「這婆爆我還不抽爆」、「官方真的是我大哥」）。
        * **🟢 +1 ~ +3 (正面滿意)**：遊戲體驗良好，對更新、活動或角色表示讚賞（例如：「這次改版還不錯」、「新角色的美術很香」）。
        * **⚪ 0 (中立客觀)**：單純的情報分享、遊戲機制探討、或是無明顯情緒的新手提問（例如：「請問這關怎麼打」、「明天維修時間確認」）。
        * **🔴 -1 ~ -3 (負面抱怨)**：對遊戲設計、機率或小 Bug 感到不滿，但尚未到達退坑程度（例如：「這掉落率真的感人」、「連線又斷了，煩死」）。
        * **🔴 -4 ~ -5 (極度憤怒/公關危機)**：強烈的退坑宣言、要求退款、對營運團隊的嚴重指責或號召抵制（例如：「垃圾吃相有夠難看」、「已檢舉退款，準備解除安裝」）。
        """)

st.divider()

if filtered_df.empty:
    st.info("目前的篩選條件下沒有符合的文章，請調整左側的過濾條件。")
    st.stop()

# ==========================================
# 5. 戰情室展示 (1)：輿情聲量與情緒分佈
# ==========================================
st.subheader("📊 戰情室展示 (1)：聲量趨勢與情緒分佈")

col_trend, col_pie = st.columns([2, 1])

with col_trend:
    st.write("**聲量與平均情緒雙軸趨勢**")
    daily_trend = filtered_df.groupby('date').agg(
        文章量=('uuid', 'count'), 平均情緒=('sentiment_score', 'mean')
    ).reset_index()

    base = alt.Chart(daily_trend).encode(x=alt.X('date:T', title='日期'))

    bar = base.mark_bar(opacity=0.4, color='#6baed6', size=25).encode(
        y=alt.Y('文章量:Q', title='討論總筆數 (留言+主文)', axis=alt.Axis(titleColor='#6baed6'))
    )

    line = base.mark_line(color='#d62728', strokeWidth=3, point=alt.OverlayMarkDef(size=100, color='#d62728')).encode(
        y=alt.Y('平均情緒:Q', title='情緒分數 (Score)', scale=alt.Scale(domain=[-5, 5]), axis=alt.Axis(titleColor='#d62728')),
        tooltip=['date:T', '文章量:Q', alt.Tooltip('平均情緒:Q', format='.2f')]
    )

    combo_chart = alt.layer(bar, line).resolve_scale(y='independent').properties(height=350)
    st.altair_chart(combo_chart, use_container_width=True)

with col_pie:
    st.write("**情緒健康度佔比**")
    sentiment_counts = filtered_df['sentiment_category'].value_counts().reset_index()
    sentiment_counts.columns = ['情緒', '數量']
    
    color_scale = alt.Scale(
        domain=['正面 (Positive)', '中立 (Neutral)', '負面 (Negative)'],
        range=['#2ca02c', '#a6b1bd', '#d62728'] 
    )
    
    donut_chart = alt.Chart(sentiment_counts).mark_arc(innerRadius=60).encode(
        theta=alt.Theta(field="數量", type="quantitative"),
        color=alt.Color(field="情緒", type="nominal", scale=color_scale, legend=alt.Legend(orient="bottom", title="")),
        tooltip=['情緒', '數量']
    ).properties(height=350)
    
    st.altair_chart(donut_chart, use_container_width=True)

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
        donut2 = alt.Chart(topic_df).mark_arc(innerRadius=60).encode(
            theta=alt.Theta(field="數量", type="quantitative"),
            color=alt.Color(field="議題", type="nominal", scale=alt.Scale(scheme='category20')),
            tooltip=['議題', '數量']
        ).properties(height=250)
        st.altair_chart(donut2, use_container_width=True)
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
# 7. 戰情室展示 (3)：競品社群情緒穩定度對比
# ==========================================
if selected_board == "全部" and len(all_boards) > 1:
    st.subheader("⚔️ 戰情室展示 (3)：競品社群情緒穩定度對比")
    
    st.markdown("""
    > 💡 **分析說明**：
    > 考量不同遊戲的「改版時程」與「活動週期」不一致，直接對比單日聲量容易產生偏差。
    > 因此，本區塊屏除時間軸，直接以**「社群情緒穩定度 (Community Volatility)」**進行宏觀的品牌體質健檢。
    > **看圖秘訣**：盒鬚圖的區塊越寬，代表該遊戲的玩家評價越兩極（容易引發爭議）；區塊越窄，代表玩家評價越趨於一致。
    """)
    
    st.write("**📦 社群情緒分數分佈圖**")
    
    box_chart = alt.Chart(filtered_df).mark_boxplot(extent='min-max', size=40).encode(
        x=alt.X('sentiment_score:Q', title='情緒分數分佈', scale=alt.Scale(domain=[-5, 5])),
        y=alt.Y('board_name:N', title='', sort=alt.EncodingSortField(field="sentiment_score", op="mean", order="descending")),
        color=alt.Color('board_name:N', legend=None, scale=alt.Scale(scheme='set1')),
        tooltip=['board_name:N']
    ).properties(height=400)
    
    st.altair_chart(box_chart, use_container_width=True)
        
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