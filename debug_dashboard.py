import streamlit as st
import pymysql
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(layout="wide", page_title="Streamlit 照妖鏡")

st.title("🔍 Streamlit 資料流診斷室")

# 1. 檢查資料庫連線設定
st.subheader("1. 環境變數檢查")
db_pass = os.getenv('DB_PASSWORD')
st.write(f"資料庫密碼讀取狀態: {'✅ 讀取成功' if db_pass else '❌ 讀取失敗 (None)'}")

# 2. 直接撈取原始資料 (不做任何 pandas 處理)
st.subheader("2. 原始資料庫連線測試")
try:
    conn = pymysql.connect(
        host='127.0.0.1',
        user='root',
        password=db_pass,
        db='sentiment_monitor',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    st.success("資料庫連線成功！")
    
    # 撈取前 10 筆完整資料
    sql = """
    SELECT p.title, p.created_at, s.sentiment_score
    FROM bahamut_posts p
    JOIN sentiment_results s ON p.uuid = s.post_uuid
    LIMIT 20
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        data = cursor.fetchall()
        
    conn.close()
    
    st.write(f"📊 SQL 查詢回傳筆數: **{len(data)}**")
    
    if len(data) > 0:
        st.write("📋 原始資料預覽 (前 5 筆):")
        st.table(data[:5])
        
        # 3. 測試 Pandas 轉換 (模擬 Dashboard 的過濾過程)
        st.subheader("3. 模擬 Dashboard 過濾過程")
        df = pd.DataFrame(data)
        
        # 測試 A: 轉分數
        df['score_numeric'] = pd.to_numeric(df['sentiment_score'], errors='coerce')
        failed_scores = df['score_numeric'].isna().sum()
        st.write(f"🔢 分數轉換失敗數: {failed_scores}")
        if failed_scores > 0:
            st.error(f"⚠️ 分數有問題的資料: {df[df['score_numeric'].isna()]['sentiment_score'].tolist()}")
            
        # 測試 B: 轉時間
        df['date_numeric'] = pd.to_datetime(df['created_at'], errors='coerce')
        failed_dates = df['date_numeric'].isna().sum()
        st.write(f"📅 時間轉換失敗數: {failed_dates}")
        if failed_dates > 0:
             st.error(f"⚠️ 時間有問題的資料: {df[df['date_numeric'].isna()]['created_at'].tolist()}")

        # 測試 C: 最終存活
        final_count = len(df.dropna(subset=['score_numeric', 'date_numeric']))
        st.metric("最終 Dashboard 能顯示的筆數", final_count)
        
        if final_count == 0:
            st.error("❌ 所有資料都被過濾掉了！兇手就在上面的失敗數裡！")
        else:
            st.balloons()
            st.success("✅ 資料看起來沒問題啊！回去檢查你的 dashboard.py 側邊欄是不是選錯看板了？")
            
    else:
        st.warning("⚠️ SQL 撈不到任何資料 (Count = 0)。請確認你的分析程式 (test_analysis.py) 是否真的有寫入成功。")

except Exception as e:
    st.error(f"❌ 發生錯誤: {e}")