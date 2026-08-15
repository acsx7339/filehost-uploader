import os
import sys
import time
import json
import logging
import shutil
from datetime import datetime, date
from ftplib import FTP
import requests
import yaml
from csv_exporter import export_to_csv

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("nas-uploader")

# 設定檔與資料目錄預設路徑
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/config.yaml")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
LINKS_PATH = os.path.join(DATA_DIR, "links.txt")

def load_config():
    """載入 YAML 設定檔"""
    # 支援開發環境與容器環境路徑
    paths_to_try = [CONFIG_PATH, "./config/config.yaml", "./config.yaml"]
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    logger.info(f"成功載入設定檔: {path}")
                    return config
            except Exception as e:
                logger.error(f"讀取設定檔 {path} 失敗: {e}")
    logger.error("找不到任何設定檔，系統將終止。")
    sys.exit(1)

def load_history():
    """載入歷史紀錄 JSON"""
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "files" not in data:
                    data["files"] = {}
                if "daily_stats" not in data:
                    data["daily_stats"] = {}
                return data
        except Exception as e:
            logger.error(f"讀取 history.json 失敗 (可能毀損)，建立新紀錄: {e}")
    
    return {"files": {}, "daily_stats": {}}

def save_history(history):
    """儲存歷史紀錄 JSON"""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"寫入 history.json 失敗: {e}")

def check_file_stable(file_path, stable_time, size_cache):
    """
    確認檔案大小是否已經穩定 (即寫入完成)
    size_cache 結構: {file_path: (last_size, last_time)}
    """
    try:
        current_size = os.path.getsize(file_path)
    except OSError:
        # 檔案可能被暫時鎖定或移除
        return False

    current_time = time.time()
    
    if file_path not in size_cache:
        size_cache[file_path] = (current_size, current_time)
        logger.info(f"偵測到新檔案: {os.path.basename(file_path)}，大小: {current_size} bytes，開始監控寫入狀態...")
        return False
    
    last_size, last_time = size_cache[file_path]
    
    if current_size != last_size:
        # 檔案仍在長大，更新快取
        size_cache[file_path] = (current_size, current_time)
        logger.debug(f"檔案 {os.path.basename(file_path)} 寫入中 (大小變更: {last_size} -> {current_size})")
        return False
    
    # 大小相同，檢查時間是否達到穩定閾值
    if current_time - last_time >= stable_time:
        # 已穩定
        return True
    
    return False

# ==================== KatFile API / FTP 區 ====================

def get_katfile_storage_left(api_domain, api_key):
    """
    透過 KatFile API 查詢剩餘儲存空間 (bytes)
    """
    url = f"https://{api_domain}/api/account/info?key={api_key}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("msg") == "OK" and "result" in data:
                storage_left = data["result"].get("storage_left")
                # 如果為無限制，可能是 "inf" 字串或 None
                if storage_left == "inf" or storage_left is None:
                    return float("inf")
                return int(storage_left)
    except Exception as e:
        logger.error(f"查詢 KatFile 剩餘空間失敗: {e}")
    return float("inf") # 失敗時預設回傳無限，以避免阻擋上傳，但會記錄錯誤

def get_katfile_uploaded_today(history):
    """獲取今日 KatFile 已上傳的 byte 數"""
    today_str = date.today().isoformat()
    stats = history.get("daily_stats", {}).get(today_str, {})
    return stats.get("katfile_uploaded_bytes", 0)

def add_katfile_uploaded_today(history, file_size):
    """累加今日 KatFile 上傳位元組數"""
    today_str = date.today().isoformat()
    if "daily_stats" not in history:
        history["daily_stats"] = {}
    if today_str not in history["daily_stats"]:
        history["daily_stats"][today_str] = {"katfile_uploaded_bytes": 0}
    
    history["daily_stats"][today_str]["katfile_uploaded_bytes"] += file_size

def upload_to_katfile_ftp(host, username, password, file_path):
    """上傳檔案至 KatFile FTP"""
    filename = os.path.basename(file_path)
    logger.info(f"[KatFile] 開始上傳 {filename} 至 FTP...")
    try:
        with FTP(host, timeout=60) as ftp:
            ftp.login(user=username, passwd=password)
            with open(file_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
        logger.info(f"[KatFile] FTP 上傳完成: {filename}")
        return True
    except Exception as e:
        logger.error(f"[KatFile] FTP 上傳失敗: {e}")
        return False

def get_katfile_download_link(api_domain, api_key, filename, max_retries=6, delay=15):
    """
    上傳完成後，輪詢 API 獲取 KatFile 下載連結
    """
    url = f"https://{api_domain}/api/file/list?key={api_key}&name={filename}"
    logger.info(f"[KatFile] 開始查詢下載連結 ({filename})...")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get("msg") == "OK" and "result" in data:
                    files = data["result"].get("files", [])
                    # 搜尋符合檔名的檔案
                    for f in files:
                        if f.get("name") == filename:
                            link = f.get("link")
                            if link:
                                logger.info(f"[KatFile] 成功獲取下載連結: {link}")
                                return link
            logger.info(f"[KatFile] 尚未在檔案列表找到 {filename}，等候後台處理... (嘗試 {attempt}/{max_retries})")
        except Exception as e:
            logger.error(f"[KatFile] 查詢 API 異常 (嘗試 {attempt}/{max_retries}): {e}")
        
        if attempt < max_retries:
            time.sleep(delay)
            
    logger.warning(f"[KatFile] 超時未獲取 {filename} 的下載連結，將於下次掃描時重試 API 查詢。")
    return None

# ==================== Rapidgator API / FTP 區 ====================

def get_rapidgator_sid(username, password):
    """登入 Rapidgator 獲取 session ID (sid)"""
    url = f"https://rapidgator.net/api/user/login?username={username}&password={password}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # 依據 API 回應欄位格式
            if "response" in data and "sid" in data["response"]:
                return data["response"]["sid"]
            elif "result" in data and "sid" in data["result"]:
                return data["result"]["sid"]
            logger.error(f"[Rapidgator] 登入回應格式不符: {data}")
    except Exception as e:
        logger.error(f"[Rapidgator] 登入 API 呼叫失敗: {e}")
    return None

def upload_to_rapidgator_ftp(host, username, password, file_path):
    """上傳檔案至 Rapidgator FTP"""
    filename = os.path.basename(file_path)
    logger.info(f"[Rapidgator] 開始上傳 {filename} 至 FTP...")
    try:
        with FTP(host, timeout=60) as ftp:
            ftp.login(user=username, passwd=password)
            with open(file_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
        logger.info(f"[Rapidgator] FTP 上傳完成: {filename}")
        return True
    except Exception as e:
        logger.error(f"[Rapidgator] FTP 上傳失敗: {e}")
        return False

def get_rapidgator_download_link(username, password, filename, max_retries=6, delay=15):
    """
    登入後獲取根目錄檔案列表，搜尋檔名並組合下載連結
    """
    logger.info(f"[Rapidgator] 開始查詢下載連結 ({filename})...")
    for attempt in range(1, max_retries + 1):
        sid = get_rapidgator_sid(username, password)
        if not sid:
            logger.warning(f"[Rapidgator] 無法獲取 sid，等候重試... (嘗試 {attempt}/{max_retries})")
            time.sleep(delay)
            continue
            
        url = f"https://rapidgator.net/api/folder/content?sid={sid}"
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                # 取得檔案列表
                files = []
                if "response" in data and "files" in data["response"]:
                    files = data["response"]["files"]
                elif "result" in data and "files" in data["result"]:
                    files = data["result"]["files"]
                
                for f in files:
                    if f.get("name") == filename:
                        file_id = f.get("id") or f.get("file_id")
                        if file_id:
                            # 組合 Rapidgator 下載連結格式
                            link = f"https://rapidgator.net/file/{file_id}/{filename}.html"
                            logger.info(f"[Rapidgator] 成功獲取下載連結: {link}")
                            return link
            logger.info(f"[Rapidgator] 尚未在根目錄找到 {filename}，等候後台處理... (嘗試 {attempt}/{max_retries})")
        except Exception as e:
            logger.error(f"[Rapidgator] 查詢 API 異常 (嘗試 {attempt}/{max_retries}): {e}")
        
        if attempt < max_retries:
            time.sleep(delay)
            
    logger.warning(f"[Rapidgator] 超時未獲取 {filename} 的下載連結，將於下次掃描時重試 API 查詢。")
    return None

# ==================== 主工作流 ====================

def write_link_to_txt(filename, kat_link, rg_link):
    """將上傳成功的下載連結寫入 links.txt"""
    os.makedirs(os.path.dirname(LINKS_PATH), exist_ok=True)
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = (
        f"[{time_str}] 檔名: {filename}\n"
        f"KatFile: {kat_link if kat_link else '未啟用/跳過'}\n"
        f"Rapidgator: {rg_link if rg_link else '未啟用/跳過'}\n"
        f"{'-'*40}\n"
    )
    try:
        with open(LINKS_PATH, "a", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"連結已寫入 links.txt: {filename}")
    except Exception as e:
        logger.error(f"寫入 links.txt 失敗: {e}")

def process_file(file_path, config, history):
    """處理單個已穩定檔案的上傳與連結查詢"""
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    # 初始化此檔案在 history.json 的狀態
    if filename not in history["files"]:
        history["files"][filename] = {
            "size": file_size,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "katfile": {"status": "pending", "link": None},
            "rapidgator": {"status": "pending", "link": None}
        }
    
    file_state = history["files"][filename]
    
    # 讀取設定檔中各平台是否啟用
    kat_conf = config.get("katfile", {})
    rg_conf = config.get("rapidgator", {})
    
    kat_enabled = kat_conf.get("enabled", False)
    rg_enabled = rg_conf.get("enabled", False)
    
    # 1. 處理 KatFile 上傳
    if kat_enabled and file_state["katfile"]["status"] != "success":
        # 進行容量與額度限制檢查
        storage_left = get_katfile_storage_left(kat_conf.get("api_domain", "katfile.biz"), kat_conf.get("api_key"))
        daily_limit_gb = kat_conf.get("daily_limit_gb", 10)
        daily_limit_bytes = daily_limit_gb * 1024 * 1024 * 1024
        uploaded_today = get_katfile_uploaded_today(history)
        
        if storage_left < file_size:
            logger.warning(f"[KatFile] 剩餘空間不足! 剩餘: {storage_left} bytes, 檔案大小: {file_size} bytes. 跳過上傳。")
            file_state["katfile"]["status"] = "skipped"
            file_state["katfile"]["error"] = "Storage full"
        elif uploaded_today + file_size > daily_limit_bytes:
            logger.warning(
                f"[KatFile] 達到每日上傳限額 ({daily_limit_gb}GB)! "
                f"今日已傳: {uploaded_today / (1024**3):.2f} GB, 檔案大小: {file_size / (1024**3):.2f} GB. 本日暫停上傳。"
            )
            # 保持 pending，明日重試
            file_state["katfile"]["status"] = "pending"
        else:
            # 執行上傳
            success = upload_to_katfile_ftp(
                kat_conf.get("ftp_host", "ftp.katfile.com"),
                kat_conf.get("username"),
                kat_conf.get("password"),
                file_path
            )
            if success:
                # 呼叫 API 獲取下載連結
                link = get_katfile_download_link(
                    kat_conf.get("api_domain", "katfile.biz"),
                    kat_conf.get("api_key"),
                    filename
                )
                if link:
                    file_state["katfile"]["status"] = "success"
                    file_state["katfile"]["link"] = link
                    file_state["katfile"].pop("error", None)
                    # 累計上傳流量
                    add_katfile_uploaded_today(history, file_size)
                else:
                    file_state["katfile"]["status"] = "failed"
                    file_state["katfile"]["error"] = "Failed to fetch API link"
            else:
                file_state["katfile"]["status"] = "failed"
                file_state["katfile"]["error"] = "FTP upload failed"
                
        save_history(history)
        
    # 2. 處理 Rapidgator 上傳
    if rg_enabled and file_state["rapidgator"]["status"] != "success":
        success = upload_to_rapidgator_ftp(
            rg_conf.get("ftp_host", "upload.rapidgator.net"),
            rg_conf.get("username"),
            rg_conf.get("password"),
            file_path
        )
        if success:
            link = get_rapidgator_download_link(
                rg_conf.get("username"),
                rg_conf.get("password"),
                filename
            )
            if link:
                file_state["rapidgator"]["status"] = "success"
                file_state["rapidgator"]["link"] = link
                file_state["rapidgator"].pop("error", None)
            else:
                file_state["rapidgator"]["status"] = "failed"
                file_state["rapidgator"]["error"] = "Failed to fetch API link"
        else:
            file_state["rapidgator"]["status"] = "failed"
            file_state["rapidgator"]["error"] = "FTP upload failed"
            
        save_history(history)
        
    # 3. 檢查最終歸檔與輸出
    kat_status = file_state["katfile"]["status"] if kat_enabled else "success"
    rg_status = file_state["rapidgator"]["status"] if rg_enabled else "success"
    
    # 只要兩邊都處理完成 (不論 success 還是 skipped)
    if kat_status in ["success", "skipped"] and rg_status in ["success", "skipped"]:
        logger.info(f"檔案 {filename} 全平台處理結束，開始歸檔寫入連結...")
        kat_link = file_state["katfile"]["link"] if kat_status == "success" else None
        rg_link = file_state["rapidgator"]["link"] if rg_status == "success" else None
        
        # 寫入文字紀錄
        write_link_to_txt(filename, kat_link, rg_link)
        
        # 寫入 CSV 發文紀錄
        csv_path = config.get("system", {}).get("csv_export_path", "/app/data/posts.csv")
        post_template = config.get("csv", {}).get("post_template", "")
        if post_template:
            export_to_csv(csv_path, filename, file_size, kat_link, rg_link, post_template)
        else:
            logger.warning(f"尚未設定 CSV 發文模板 (csv.post_template)，跳過寫入 CSV: {filename}")
        
        # 移動檔案到已完成目錄
        completed_dir = config["system"]["completed_dir"]
        os.makedirs(completed_dir, exist_ok=True)
        dest_path = os.path.join(completed_dir, filename)
        
        try:
            shutil.move(file_path, dest_path)
            logger.info(f"檔案已歸檔至: {dest_path}")
            # 完成後可將紀錄從 active 佇列標記為 completed 狀態
            file_state["archived"] = True
            file_state["archived_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"移動檔案 {filename} 至完成區失敗: {e}")
            
        save_history(history)

def main():
    logger.info("NAS 免空自動上傳系統啟動...")
    config = load_config()
    
    # 初始化快取與工作目錄
    size_cache = {}
    system_conf = config.get("system", {})
    watch_dir = system_conf.get("watch_dir", "/watch")
    completed_dir = system_conf.get("completed_dir", "/completed")
    scan_interval = system_conf.get("scan_interval", 30)
    stable_time = system_conf.get("file_stable_time", 10)
    
    # 確保資料夾存在
    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(completed_dir, exist_ok=True)
    
    while True:
        try:
            # 每次掃描前重新載入紀錄
            history = load_history()
            
            # 遞迴掃描 watch 資料夾下的檔案
            found_files = []
            for root, _, files in os.walk(watch_dir):
                for f in files:
                    # 排除隱藏檔案 (例如 Mac 的 .DS_Store 或暫存檔)
                    if f.startswith("."):
                        continue
                    found_files.append(os.path.join(root, f))
            
            stable_files = []
            for fp in found_files:
                filename = os.path.basename(fp)
                # 如果該檔案已經在 history 中被記錄為已歸檔完成，就跳過
                file_state = history.get("files", {}).get(filename)
                if file_state and file_state.get("archived", False):
                    continue
                
                # 檢查寫入完成狀態
                if check_file_stable(fp, stable_time, size_cache):
                    stable_files.append(fp)
            
            # 清理 size_cache 中已經不存在於監控區的檔案快取，防止記憶體洩漏
            current_found_set = set(found_files)
            for cached_path in list(size_cache.keys()):
                if cached_path not in current_found_set:
                    size_cache.pop(cached_path, None)
            
            # 開始依序處理寫入完畢的檔案
            if stable_files:
                logger.info(f"本輪掃描發現 {len(stable_files)} 個可上傳檔案，開始處理...")
                for fp in stable_files:
                    try:
                        process_file(fp, config, history)
                    except Exception as e:
                        logger.error(f"處理檔案 {os.path.basename(fp)} 遇到未預期錯誤: {e}", exc_info=True)
            
        except Exception as e:
            logger.error(f"掃描循環發生異常: {e}", exc_info=True)
            
        time.sleep(scan_interval)

if __name__ == "__main__":
    main()
