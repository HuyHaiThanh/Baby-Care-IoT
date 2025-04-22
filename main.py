# File: main.py
# Chương trình chính của client photo

import os
import sys
import tkinter as tk
import asyncio
import threading
import logging
from photo_client import PhotoClient, start_client
from gui import create_gui
from config import DOWNLOAD_DIR

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('main')

def main():
    """Hàm chính để khởi động ứng dụng"""
    try:
        # Đảm bảo thư mục tồn tại
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        # Khởi tạo client trong thread riêng
        client = start_client()
        
        # Tạo giao diện
        root = create_gui(client)
        
        # Chạy mainloop của Tkinter
        root.mainloop()
        
    except Exception as e:
        logger.error(f"Lỗi khi khởi động ứng dụng: {e}")
        import traceback
        traceback.print_exc()
        
        # Hiển thị thông báo lỗi
        if 'root' in locals() and root:
            tk.messagebox.showerror("Lỗi", f"Lỗi khi khởi động ứng dụng: {e}")
        
        # Thoát với mã lỗi
        sys.exit(1)

if __name__ == "__main__":
    main()