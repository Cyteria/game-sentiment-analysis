import os
import time

print("🚀 開始執行自動化管線...")

print("\n--- [階段 1] 啟動爬蟲 ---")
# 呼叫爬蟲程式
os.system("python genshin_wuthering_crawler.py")

print("\n--- 等待 5 秒讓資料庫緩衝 ---")
time.sleep(5)

print("\n--- [階段 2] 啟動情緒分析 ---")
# 呼叫分析程式
os.system("python groq_analysis.py")

print("\n🎉 全部任務執行完畢！")