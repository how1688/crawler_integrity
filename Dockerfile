# 使用官方 Python 基底映像
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝必要套件 (Chromium + Chromedriver + 依賴庫)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxtst6 \
    libgbm1 \
    libasound2 \
    xdg-utils \
    wget \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 複製需求檔案並安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼
COPY . .

# 預設環境變數 (讓 selenium 找到 chromium)
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver

# 啟動程式 (修改成你的主程式名稱)
CMD ["python", "schedule_test.py"]
