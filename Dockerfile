FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 設定時區為台北
ENV TZ=Asia/Taipei
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 複製依賴套件檔並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製主程式碼
COPY src/ ./src/

# 建立掛載資料夾的預備目錄
RUN mkdir -p /watch /completed /app/config /app/data

# 啟動命令
CMD ["python", "-u", "src/main.py"]
