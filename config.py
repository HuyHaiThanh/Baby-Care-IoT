# File: config.py
# Cấu hình cho client photo

import os

# Thiết lập server
SERVER_HOST = "localhost"  # Địa chỉ IP của Raspberry Pi 2B, thay đổi theo nhu cầu
SERVER_PORT = 8000         # Port cho HTTP API
WEBSOCKET_URL = f"ws://{SERVER_HOST}:8765"  # WebSocket URL

# Cấu hình client
CLIENT_NAME = "Photo Client"

# Thư mục lưu trữ dữ liệu
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloaded_photos")

# Tạo thư mục nếu chưa tồn tại
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Cấu hình hiển thị
WINDOW_TITLE = "Baby Monitor - Photo Client"
WINDOW_SIZE = (800, 600)

# Cấu hình tải ảnh
AUTO_REFRESH = True  # Tự động làm mới ảnh
REFRESH_INTERVAL = 5  # Thời gian tự động làm mới (giây)