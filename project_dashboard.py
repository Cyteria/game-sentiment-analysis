# python3 -m streamlit run project_dashboard.py --server.port 8501 --server.address 0.0.0.0

import streamlit as st
import pymysql
import pandas as pd
import os
from dotenv import load_dotenv # 引入讀取套件

load_dotenv()
DB_PASSWORD = os.getenv("DB_PASSWORD")

# ==========================================
# 1. 資料庫連線設定
# ==========================================
DB_SETTINGS = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": "root",
    "password": DB_PASSWORD,
    "db": "sentiment_monitor",
    "charset": "utf8mb4"
}

# ==========================================
# 2. 抓資料函式
# ==========================================
def load_data():
  connection = pymysql.connect(**DB_SETTINGS)
  # 使用 pandas 直接把 SQL 結果變成一個表格 (DataFrame)
  sql = "SELECT title, content, sentiment_score, url FROM bahamut_posts WHERE sentiment_score IS NOT NULL"
  df = pd.read_sql(sql, connection)
  connection.close()
  return df

# ==========================================
# 3. 網頁介面設計 (Streamlit Magic)
# ==========================================

# 設定網頁標題
st.title("📊 原神版 & 鳴潮版 輿情監控戰情室")
st.write("即時分析巴哈姆特論壇玩家情緒")

# 載入資料
df = load_data()

# --- 區塊 A: 關鍵指標 (KPI) ---
col1, col2, col3 = st.columns(3)
total_posts = len(df)
# 定義：分數 > 0.6 算正面，< 0.4 算負面
positive_count = len(df[df['sentiment_score'] > 0.5])
negative_count = len(df[df['sentiment_score'] < 0.5])

col1.metric("總文章數", f"{total_posts} 篇")
col2.metric("正面好評", f"{positive_count} 篇", delta=f"{positive_count/total_posts:.1%}")
col3.metric("負面炎上", f"{negative_count} 篇", delta_color="inverse", delta=f"{negative_count/total_posts:.1%}")

st.divider() # 分隔線

# --- 區塊 B: 情緒分佈圖 ---
st.subheader("📈 情緒分數分佈")
# 畫一個長條圖看分數分佈
st.bar_chart(df['sentiment_score'])

# --- 區塊 C: 憤怒榜 (負評偵測) ---
st.subheader("🔥 炎上預警：最憤怒的 5 篇文章")
# 找出分數最低的前 5 筆
angry_posts = df.sort_values(by='sentiment_score').head(5)

# 顯示出來
for index, row in angry_posts.iterrows():
    # 用 expander 做成可以展開的樣子
    with st.expander(f"[{row['sentiment_score']:.2f}] {row['title']}"):
        st.write(row['content'][:200] + "...") # 只顯示前200字
        st.write(f"[點我前往原文]({row['url']})")

# --- 區塊 D: 重新整理按鈕 ---
if st.button('重新載入資料'):
    st.rerun()