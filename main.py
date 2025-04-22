# File: main.py
# Chương trình chính của client photo

import os
import sys
import tkinter as tk
import asyncio
import threading
import logging
import argparse
from photo_client import PhotoClient, start_client
from gui import create_gui
from config import DOWNLOAD_DIR
import config

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('main')

def parse_arguments():
    """Phân tích tham số dòng lệnh"""
    parser = argparse.ArgumentParser(description='Baby Monitor - Photo Client')
    parser.add_argument('--server', type=str, help='Địa chỉ IP của server')
    return parser.parse_args()

def main():
    """Hàm chính để khởi động ứng dụng"""
    try:
        # Phân tích tham số dòng lệnh
        args = parse_arguments()
        
        # Cập nhật địa chỉ server nếu được cung cấp
        websocket_url = None
        if args.server:
            logger.info(f"Sử dụng địa chỉ server: {args.server}")
            config.SERVER_HOST = args.server
            config.WEBSOCKET_URL = f"ws://{args.server}:8765"
            websocket_url = config.WEBSOCKET_URL
        
        # Đảm bảo thư mục tồn tại
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        # Khởi tạo client trong thread riêng
        client = start_client(websocket_url=websocket_url)
        
        # Tạo giao diện
        root = create_gui(client)
        
        # Cập nhật hiển thị địa chỉ server trong giao diện
        if args.server:
            # Tìm server_entry trong giao diện và cập nhật giá trị
            for widget in root.winfo_children():
                if hasattr(widget, 'server_entry'):
                    widget.server_entry.delete(0, tk.END)
                    widget.server_entry.insert(0, args.server)
        
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