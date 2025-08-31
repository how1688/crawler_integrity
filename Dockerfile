# 使用 Selenium 官方 standalone-chrome 映像
FROM selenium/standalone-chrome:latest

# 設定工作目錄
WORKDIR /app

# Railway 容器裡建立 /downloads 目錄
ENV DOWNLOAD_DIR=/downloads

# 安裝 Python
USER root
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# 複製專案需求
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 複製專案程式碼
COPY . .

# 切回 seluser（Selenium 官方映像默認使用）
USER seluser

# 執行主程式
CMD ["python3", "schedule_test.py"]