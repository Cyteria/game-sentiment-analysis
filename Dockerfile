# 1. 使用官方的 Python 輕量版基礎映像檔
FROM python:3.9-slim

# 2. 設定容器內的時區為台灣時間 (這對爬蟲排程和Log紀錄很重要！)
ENV TZ=Asia/Taipei
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 3. 設定工作目錄
WORKDIR /app

# 4. 先複製 requirements.txt 進去並安裝套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 複製剩下的所有程式碼進去
COPY . .

# 6. 設定容器啟動後要執行的指令
# 使用 shell 的 && 指令串聯，前一個成功才會執行後一個
CMD ["sh", "-c", "python -u project_fetch_baha.py; python -u project_analyze_groq.py"]