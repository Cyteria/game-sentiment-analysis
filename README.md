# 🎮 巴哈姆特遊戲輿情分析室 (Game Sentiment Analysis)

這是一個全自動化的遊戲社群輿情觀測站。本專案透過自動化爬蟲抓取巴哈姆特論壇的玩家討論，結合大語言模型 (LLM) 進行深度的情緒與語意分析，並將結果具象化為 24 小時即時更新的雲端視覺化戰情室。

🔗 **即時戰情室展示**：[點擊這裡觀看即時數據]([https://game-dashboard-service-511900659220.asia-east1.run.app/])

---

## ✨ 核心特色與架構

本專案採用**微服務架構 (Microservices)** 設計，將「資料獲取」、「AI 分析」與「前端展示」解耦，確保系統的穩定性與擴充性，並完全部署於 Google Cloud Platform (GCP)。

1. 🕷️ **自動化資料管線 (Data Pipeline)**
   - 透過 Python 爬蟲定時抓取巴哈姆特特定遊戲看板（本案抓取：鳴潮、原神）的最新文章與推噓文數據。
   - 可修改各版 ID 新增抓取不同版的資訊。
   - 使用 GCP Cloud Scheduler 設定定時任務，實現完全無人值守的自動化每日抓取。

2. 🤖 **AI 智慧語意分析 (LLM Integration)**
   - 串接 **Groq API**，利用高效能 LLM 對每一篇文章進行深度拆解。
   - 不只判斷「正/負面情緒分數」，更能精準萃取出：**討論主/次分類** (如：Bug、劇情、優化)、**目標角色** (Target Character) 以及 **核心關鍵字**。
   - 具備防呆機制：自動處理 API Rate Limit，並支援多把金鑰自動切換與「少量多餐」的批次處理邏輯。

3. 📊 **互動式視覺化儀表板 (Streamlit Dashboard)**
   - **時間趨勢追蹤**：掌握每次版本更新或炎上事件的情緒波動。
   - **整體情緒分佈**：直觀的甜甜圈圖展示社群正負面比例。
   - **熱門角色好感度排行**：精準洞察玩家對特定角色的喜惡程度。
   - **議題下鑽分析**：透過堆疊長條圖與文字雲，快速抓出玩家痛點。
   - **單篇深度檢視**：直接在介面上查看 AI 對單篇文章的詳細判讀理由與給分。

---

## 🛠️ 技術棧 (Tech Stack)

- **前端與視覺化**: Streamlit, Altair, Pandas
- **後端與資料處理**: Python 3, PyMySQL, JSON
- **AI 整合**: Groq API (LLM)
- **雲端基礎設施 (GCP)**: 
  - Google Cloud Run (容器化網頁代管與獨立任務)
  - Google Cloud SQL (MySQL 雲端資料庫)
  - Google Cloud Scheduler (自動化排程器)
- **部署工具**: Docker

---

## 📸 畫面截圖預覽

*(下方圖片如無法顯示，請確認圖片連結是否正確)*

### 1. 戰情室總覽與時間趨勢
([<img width="1708" height="818" alt="截圖 2026-03-07 凌晨1 39 51" src="https://github.com/user-attachments/assets/de97e12c-e1b1-48a3-8806-ed9e6a5761ae" />
])

### 2. 角色好感度排行與分類下鑽
([<img width="1707" height="915" alt="截圖 2026-03-07 凌晨1 40 11" src="https://github.com/user-attachments/assets/c73abbb6-4e36-4a44-af6d-cdbf530ef742" />
])

### 3. AI 單篇深度分析
([<img width="1709" height="897" alt="截圖 2026-03-07 凌晨1 42 12" src="https://github.com/user-attachments/assets/242dfdc2-d0c8-46e6-97e4-f6f5350912ff" />
])

---

## 🚀 系統部署與運行指南

### 1. 環境變數設定
請在專案根目錄建立 `.env` 檔案，並填入以下資訊：
```env
DB_PASSWORD=[資料庫密碼]
GROQ_API_KEY=[第一把Groq金鑰]
GROQ_API_KEY_2=[第二把Groq金鑰]
GROQ_API_KEY_3 .....

2. 本機開發運行 (Local Development)
安裝所需套件並啟動 Streamlit 伺服器：

Bash
pip install -r requirements.txt
streamlit run dashboard.py
(註：本機運行時，程式會自動識別環境並透過 127.0.0.1 尋找資料庫，需搭配 Cloud SQL Auth Proxy 使用)

3. 雲端部署架構 (Docker + GCP)
本專案的 Dockerfile 已分別為「定時任務 (Job)」與「網頁服務 (Web)」進行優化：

Dockerfile.web: 用於打包並部署 Streamlit 儀表板 (game-dashboard-service)。

Dockerfile.job: 用於打包後端自動化腳本，並在 Cloud Run 分拆為兩個獨立的 Job：

game-crawler-task: 專責抓取新資料。

game-analysis-task: 專責消化未分析的文章 (Batch processing)。

📝 聯絡資訊與授權 (License)
Author: [Cyteria]

GitHub: [https://github.com/Cyteria/game-sentiment-analysis/]

This project is licensed under the MIT License.
