# NAS 免空自動上傳系統 (nas-auto-uploader)

這是一套設計給 NAS 系統（如 QNAP Container Station、Synology Docker）運作的自動化免空上傳與收益系統。系統會自動監控指定的暫存區資料夾（`/watch`），在確認大檔案寫入完成後，循序透過 FTP 上傳至 **KatFile** 與 **Rapidgator**，並自動利用 API 解析取得下載連結，最後自動生成各大論壇適用的發文 CSV 檔案（`posts.csv`），並將上傳完畢的檔案移動到完成區（`/completed`）。

## 系統特點
* **極簡架構**：不依賴複雜的資料庫與多執行緒佇列，僅透過 `history.json` 狀態檔配合單執行緒循環進行檔案處理。
* **自動產生論壇發文 CSV**：自動提取檔名並將檔案大小、KatFile / Rapidgator 下載連結套入發文模板（支援 BBCode / Markdown），產出 `posts.csv` 供手動/半自動發文，徹底避開論壇防爬蟲與驗證碼機制。
* **每日額度限制保護**：支援 KatFile 每日 10GB 上傳上限檢查。當今日已上傳容量達到上限時，系統會自動暫停 KatFile 的上傳並於隔日額度重置後自動補傳，期間 Rapidgator 仍可正常上傳。
* **剩餘空間預警**：自動檢查 KatFile 帳戶剩餘儲存空間，若空間不足將跳過上傳並發出警報，防止頻寬浪費。
* **斷線續傳能力**：若上傳中途失敗或僅完成了單一平台，下次掃描會讀取 `history.json` 僅對尚未完成的平台補傳，已完成的平台不會重複上傳。

---

## 目錄結構說明

```text
nas-auto-uploader/
├── config/
│   ├── config.example.yaml  # 設定檔範本 (可複製為 config.yaml)
│   └── config.yaml          # 系統設定檔 (包含帳密、API Key、發文模板等，已納入 .gitignore)
├── src/
│   ├── main.py              # 單一主程式：包含資料夾偵測、寫入檢查、FTP 上傳與 API 查詢
│   └── csv_exporter.py      # 發文 CSV 導出模組：將免空連結與模板組合並寫入 posts.csv
├── data/
│   ├── history.json         # 紀錄檔案在上傳各平台的狀態 (自動生成)
│   ├── links.txt            # 產出下載連結的純文字紀錄檔 (自動生成)
│   └── posts.csv            # 整合發文模板與免空連結的 CSV 紀錄檔 (自動生成)
├── Dockerfile               # 用於建置 Python 應用程式鏡像
├── docker-compose.yml       # Docker Compose 設定
├── requirements.txt         # Python 依賴套件清單
├── .gitignore               # Git 忽略設定 (避免敏感帳密上傳)
└── README.md                # 專案中文說明與部署指南
```

---

## 部署與使用步驟

### 步驟一：在 NAS 上 clone 專案或複製檔案
將專案 Git clone 或複製到您的 NAS 專案目錄（例如 `/share/CACHEDEV1_DATA/Container/nas-auto-uploader`）。

### 步驟二：配置 `config/config.yaml`
複製範本檔案 `config/config.example.yaml` 為 `config/config.yaml`：
```bash
cp config/config.example.yaml config/config.yaml
```
編輯 `config/config.yaml`，填入您的平台帳號、密碼與 API 金鑰以及發文模板：

```yaml
# 系統基礎設定
system:
  watch_dir: "/watch"               # 監控資料夾路徑 (容器內虛擬路徑，請勿修改)
  completed_dir: "/completed"       # 上傳完成歸檔路徑 (容器內虛擬路徑，請勿修改)
  scan_interval: 30                 # 資料夾掃描間隔時間 (秒)
  file_stable_time: 10              # 檔案大小穩定檢測時間 (秒，確認檔案沒有在增長)
  history_path: "/app/data/history.json"
  csv_export_path: "/app/data/posts.csv"

# KatFile 平台設定
katfile:
  enabled: true                     # 是否啟用 KatFile 上傳 (true/false)
  username: "your_katfile_username" # KatFile FTP 帳號
  password: "your_katfile_password" # KatFile FTP 密碼
  api_key: "your_katfile_api_key"   # KatFile API Key
  api_domain: "katfile.biz"          # KatFile API 網域
  daily_limit_gb: 10                # 每日上傳額度限制 (GB)
  ftp_host: "ftp.katfile.com"       # KatFile FTP 伺服器主機

# Rapidgator 平台設定
rapidgator:
  enabled: true                     # 是否啟用 Rapidgator 上傳 (true/false)
  username: "your_rapidgator_username" # Rapidgator FTP 帳號
  password: "your_rapidgator_password" # Rapidgator FTP 密碼
  ftp_host: "upload.rapidgator.net" # Rapidgator FTP 伺服器主機

# CSV 發文範本設定
csv:
  post_template: |
    【檔案名稱】：{title}
    【檔案大小】：{file_size}
    
    【下載連結】：
    KatFile: [url]{katfile_url}[/url]
    Rapidgator: [url]{rapidgator_url}[/url]
    
    【解壓密碼】：無
```

### 步驟三：啟動服務
於專案目錄下執行以下 Docker 命令啟動服務：

```bash
# 建置並在背景啟動容器
docker compose up -d --build
```

查看即時運行日誌：
```bash
docker compose logs -f
```

---

## 事前準備與注意事項

* [ ] **1. 平台帳號與憑證申請**
  * **KatFile 帳號**：需註冊帳戶，並於後台啟用 PPD 分潤模式，取得 FTP 上傳密碼與 API 金鑰。
  * **Rapidgator 帳號**：需註冊帳戶，啟用分潤模式，取得 FTP 上傳密碼。
* [ ] **2. NAS 目錄掛載與權限設定**
  * 確保 NAS 上對應的 `/watch` (待上傳暫存區) 與 `/completed` (歸檔區) 已建立。
  * 確保運行 Docker 的系統使用者對上述資料夾擁有完整的**讀取與寫入 (R/W) 權限**。
