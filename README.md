# 🎮 全自動遊戲社群輿情觀測戰情室 (Game Community Sentiment Dashboard)

[![Deployed on GCP Cloud Run](https://img.shields.io/badge/Deployed%20on-GCP%20Cloud%20Run-4285F4?style=flat-square&logo=google-cloud)](https://game-dashboard-service-511900659220.asia-east1.run.app/)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square&logo=python&logoColor=white)]()
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)]()

> **24 小時無人值守的數據中心，將冰冷的文字即時轉化為商業洞察。**

本專案致力於打造一個全自動化的遊戲社群輿情觀測站。透過定時抓取指標性論壇數據，並導入大型語言模型（LLM）進行深度語意解析，幫助遊戲營運與行銷團隊一眼看穿「新角色受歡迎程度」或潛在的「炎上趨勢」，將社群聲音轉化為具體的商業決策依據。

🔗 **[點此訪問即時戰情室 (Live Demo)](https://game-dashboard-service-511900659220.asia-east1.run.app/)**

---

## ✨ 核心特色 (Key Features)

* 🕷️ **全自動化爬蟲 (Automated Crawlers)**
    * 定時抓取巴哈姆特 (gamer.com.tw) 等指標性遊戲看板。
    * 無需人工介入，確保資料來源 24 小時不間斷，掌握第一手社群動態。
* 🧠 **AI 智慧大腦 (AI Smart Brain)**
    * 導入大型語言模型 (LLM) 進行深度語意解析，精準判讀玩家真實情緒（Sentiment）與發文意圖（Intention）。
    * 超越傳統字典或字串比對，能精準萃取上下文中的關鍵字，並具備完善的停用詞（Stop Words）過濾機制，排除系統干擾雜訊。
* 📊 **即時戰情室 (Real-Time Situation Room)**
    * 透過 Streamlit 打造互動式資料視覺化儀表板。
    * 提供情緒分佈圓餅圖、輿情熱度趨勢線、以及精煉後的熱門關鍵字文字雲，一眼看穿社群風向。

---

## 🛠️ 技術架構 (Tech Stack)

* **前端與視覺化 (Frontend & Visualization):** Streamlit
* **後端與資料處理 (Backend & Data Processing):** Python, Pandas
* **自然語言處理 (NLP):** LLM API (情緒與意圖分析)、Jieba (斷詞與停用詞過濾)
* **資料獲取 (Data Pipeline):** Python Web Scraping (Requests / BeautifulSoup)
* **資料庫 (Database):** 關聯式 / 非關聯式資料庫 (MySQL / MongoDB)
* **部署與維運 (Deployment & DevOps):** Docker, Google Cloud Platform (GCP Cloud Run)

---

## 🚀 快速開始 (Getting Started)

### 1. 複製專案 (Clone the repository)
```bash
git clone [https://github.com/Cyteria/game-sentiment-analysis.git](https://github.com/Cyteria/game-sentiment-analysis.git)
cd your-repo-name
```

### 2. 安裝依賴套件 (Install dependencies)
建議使用虛擬環境 (Virtual Environment) 進行安裝：
```bash
pip install -r requirements.txt
```

### 3. 環境變數設定 (Environment Variables)
請在根目錄建立 .env 檔案，並填入必要的 API 金鑰與資料庫連線資訊：

```
GROQ_API_KEY=your_api_key_1
GROQ_API_KEY_2=your_api_key_2
...
DB_PASSWORD=your_password
GOOGLE_API_KEY=your_google_api_key
```

### 4. 啟動本機儀表板 (Run Streamlit App Locally)

```bash
streamlit run dashboard.py
```

執行後，如果在本地運行，請開啟瀏覽器前往 http://localhost:8501 即可查看畫面。

本案支援雲端環境判斷，部署在 GCP 雲端上也可執行。

📂 專案結構 (Project Structure)
Plaintext
├── dashboard.py          # Streamlit 儀表板主程式
├── scraper/              # 巴哈姆特自動化爬蟲模組
├── nlp_processing/       # LLM API 串接與語意解析邏輯
├── data_cleaning/        # 包含 stop_words.txt 與資料前處理指令碼
├── requirements.txt      # Python 依賴套件清單
├── Dockerfile            # GCP Cloud Run 部署用 Docker 設定檔
└── README.md             # 專案說明文件

👨‍💻 開發人員
[Cyter] - Data Engineering
