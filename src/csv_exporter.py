import csv
import os
import logging
from datetime import datetime

logger = logging.getLogger("nas-uploader")

def format_size(size_bytes):
    """將 byte 轉換為易讀的格式"""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = 0
    p = pow(1024, i)
    s = round(size_bytes / p, 2)
    while s >= 1024 and i < len(size_name)-1:
        i += 1
        p = pow(1024, i)
        s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_filename_without_ext(filename):
    """取得不含副檔名的檔案名稱，當作預設標題"""
    return os.path.splitext(filename)[0]

def export_to_csv(csv_path, filename, file_size, kat_link, rg_link, template):
    """
    將檔案資訊套用發文樣板後，寫入至 CSV 檔
    """
    title = get_filename_without_ext(filename)
    human_size = format_size(file_size)
    
    # 防呆，避免連結為 None 導致套用格式失敗
    kat_link_str = kat_link if kat_link else "無"
    rg_link_str = rg_link if rg_link else "無"
    
    # 套用發文模板
    content = template.format(
        title=title,
        file_size=human_size,
        katfile_url=kat_link_str,
        rapidgator_url=rg_link_str
    )
    
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 寫入 CSV
    # 欄位：file_name,title,content,katfile_url,rapidgator_url,created_at,status
    headers = ["file_name", "title", "content", "katfile_url", "rapidgator_url", "created_at", "status"]
    
    file_exists = os.path.exists(csv_path)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    try:
        with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            
            # 若檔案不存在則先寫入標頭
            if not file_exists:
                writer.writeheader()
                
            writer.writerow({
                "file_name": filename,
                "title": title,
                "content": content,
                "katfile_url": kat_link_str,
                "rapidgator_url": rg_link_str,
                "created_at": created_at,
                "status": "Pending"
            })
            logger.info(f"已成功將 {filename} 發文資訊寫入 {csv_path}")
    except Exception as e:
        logger.error(f"寫入 CSV 失敗 ({filename}): {e}")
