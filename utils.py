import re
from bs4 import BeautifulSoup

def clean_text(html_content):
    """
    資料清洗：移除 HTML、網址、多餘空白，保留純文字給 AI 讀。
    """
    if not html_content:
        return ""

    # 1. 移除 HTML 標籤
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")

    # 2. 移除網址
    text = re.sub(r'http\S+', '', text)

    # 3. 移除連續的空白或換行，變成一行文字
    text = re.sub(r'\s+', ' ', text).strip()

    return text