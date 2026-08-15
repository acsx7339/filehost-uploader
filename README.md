# NAS 免空自動上傳系統 (nas-auto-uploader)

這是一套設計給 NAS 系統（如 QNAP Container Station、Synology Docker）運作的自動化免空上傳與收益系統。系統會自動監控指定的暫存區資料夾（`/watch`），在確認大檔案寫入完成後，循序透過 FTP 上傳至 **KatFile** 與 **Rapidgator**，並自動利用 API 解析取得下載連結寫入記錄檔（`links.txt`），最後將上傳完畢的檔案移動到完成區（`/completed`）。

## 系統特點
* **極簡架構**：不依賴複雜的資料庫與多執行緒佇列，僅透過 `history.json` 狀態檔配合單執行緒循環進行檔案處理。
* **每日額度限制保護**：支援 KatFile 每日 10GB 上傳上限檢查。當今日已上傳容量達到上限時，系統會自動暫停 KatFile 的上傳並於隔日額度重置後自動補傳，期間 Rapidgator 仍可正常上傳。
* **剩餘空間預警**：自動檢查 KatFile 帳戶剩餘儲存空間，若空間不足將跳過上傳並發出警報，防止頻寬浪費。
* **斷線續傳能力**：若上傳中途失敗或僅完成了單一平台，下次掃描會讀取 `history.json` 僅對尚未完成的平台補傳，已完成的平台不會重複上傳。

---

## 目錄結構說明

```text
nas-auto-uploader/
├── config/
│   └── config.yaml          # 系統設定檔 (包含帳密、API Key、監控路徑等)
├── src/
│   └── main.py              # 單一主程式：包含資料夾偵測、寫入檢查、FTP 上傳與 API 查詢
├── data/
│   ├── history.json         # 紀錄檔案在上傳各平台的狀態 (自動生成)
│   └── links.txt            # 產出下載連結的文字紀錄檔 (自動生成)
├── Dockerfile               # 用於建置 Python 應用程式鏡像
├── docker-compose.yml       # Docker Compose 設定，掛載 NAS 資料夾
├── requirements.txt         # Python 依賴套件清單
└── README.md                # 專案中文說明與部署指南
```

---

## 部署與使用步驟

### 步驟一：在 NAS 上建立與準備資料夾
將專案複製到您的 NAS 專案目錄（例如 `/share/CACHEDEV1_DATA/Container/nas-auto-uploader`），確保該目錄下有以下結構：
1. `src/`：存放 Python 程式碼的目錄（已包含 `main.py`）。系統會將其掛載至容器，方便您未來直接修改程式碼，不需重新 Build 容器。
2. `watch/`：您手動建立的資料夾，放置待上傳檔案的暫存監控區。
3. `completed/`：您手動建立的資料夾，上傳成功後，檔案會自動被移動到這裡歸檔。
4. `config/`：放置 `config.yaml` 的設定目錄。
5. `data/`：存放 `history.json` 狀態紀錄檔與產生的下載連結紀錄（`links.txt`）。


### 步驟二：配置 `config/config.yaml`
在 `config/` 資料夾下建立 `config.yaml`，並填入您的平台帳號、密碼與 API 金鑰：

```yaml
# 系統基礎設定
system:
  watch_dir: "/watch"               # 監控資料夾路徑 (容器內虛擬路徑，請勿修改)
  completed_dir: "/completed"       # 上傳完成歸檔路徑 (容器內虛擬路徑，請勿修改)
  scan_interval: 30                 # 資料夾掃描間隔時間 (秒)
  file_stable_time: 10              # 檔案大小穩定檢測時間 (秒，確認檔案沒有在增長)

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
```

### 步驟三：啟動服務
將專案檔案上傳至 NAS，並於專案目錄下執行以下 Docker 命令啟動服務：

```bash
# 建置並在背景啟動容器
docker-compose up -d --build
```

您也可以使用以下命令查看即時運行日誌：
```bash
docker-compose logs -f
```

---

## 本機測試指南 (開發人員)

若您想在本機進行模擬測試，可按照以下步驟操作：

1. 建立 Python 虛擬環境並安裝依賴：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. 執行模擬測試腳本（該腳本會 Mock FTP 上傳與 HTTP API 請求，不需要真實帳密即可驗證邏輯）：
   ```bash
   # 請依實際路徑執行測試腳本，如在專案根目錄下
   python3 <本機測試腳本路徑>/test_uploader.py
   ```


## 0. 事前準備與規劃事項

在開始實作與部署系統前，請確保完成以下準備工作：

* [ ] **1. 平台帳號與憑證申請**
  * **KatFile 帳號**：需註冊帳戶，並於後台啟用 PPD 分潤模式，取得 FTP 上傳密碼與 [API 金鑰](https://katfile.com/?op=my_account)。
  * **Rapidgator 帳號**：需註冊帳戶，啟用分潤模式，取得 FTP 上傳密碼與 API 呼叫權限。
* [ ] **2. NAS 目錄結構建立**
  * 在 NAS 上建立專案根目錄：`/share/CACHEDEV1_DATA/Container/nas-auto-uploader`。
  * 在其下建立子目錄：
    * `watch` (暫存監控區)
    * `completed` (上傳完成歸檔區)
    * `config` (放置系統設定檔)
    * `data` (放置產出的連結紀錄檔)
* [ ] **3. NAS 權限設定**
  * 確保運行 Docker 的系統使用者對上述資料夾擁有完整的**讀取與寫入 (R/W) 權限**，避免容器內程式因權限不足無法移動檔案或寫入 `links.txt`。
* [ ] **4. 網路連線確認**
  * 確認 NAS 的防火牆與外部連線設定，允許對外連接 `ftp.katfile.com` 與 `upload.rapidgator.net` 的 FTP 傳輸埠 (Port 21)，以及 HTTPS 的 API 呼叫。
