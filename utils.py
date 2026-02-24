import re

def clean_text(text):
    """
    資料清洗：移除網址、社群 ID、樓層標籤、多餘空白，保留純文字給 AI 讀。
    注意：因為爬蟲階段已經移除了 HTML，這裡不需要再用 BeautifulSoup。
    """
    if not text:
        return ""

    # 1. 移除網址 (含標準 http/https, 缺損 ://, 以及 www. 開頭)
    text = re.sub(r'(?:https?://|://|www\.)[a-zA-Z0-9\.\-\/\?\&\=\_\%\+\#\~]+', '', text)

    # 2. 移除社群 ID (例如 @Username)
    text = re.sub(r'@[\w]+', '', text)

    # 3. 移除巴哈樓層引用標籤 (如 #B2:3789633#)
    text = re.sub(r'#B\d+:\d+#', '', text)

    # 4. 移除連續的空白或換行，變成一行文字 (讓 AI 讀起來更順)
    text = re.sub(r'\s+', ' ', text).strip()

    return text