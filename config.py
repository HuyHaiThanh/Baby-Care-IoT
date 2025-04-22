# File: config.py
# Cấu hình cho server trên Raspberry Pi 2B

import os

# Thiết lập server
SERVER_HOST = "0.0.0.0"  # Lắng nghe trên tất cả các giao diện mạng
SERVER_PORT = 8000       # Port cho HTTP API
WEBSOCKET_PORT = 8765    # Port cho WebSocket

# Thông tin thiết bị
DEVICE_NAME = "Baby Monitor Pi"

# Thư mục lưu trữ dữ liệu
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_DIR = os.path.join(BASE_DIR, "camera_data/photos")
AUDIO_DIR = os.path.join(BASE_DIR, "camera_data/audio")
ARCHIVE_DIR = os.path.join(BASE_DIR, "camera_data/archive")
TEMP_DIR = os.path.join(BASE_DIR, "camera_data/temp")  # Thư mục lưu trữ tạm thời

# Khoảng thời gian giữa các lần chụp ảnh và ghi âm (giây)
PHOTO_INTERVAL = 10  # 10 giây/lần
AUDIO_INTERVAL = 8   # 8 giây/lần (bao gồm cả thời gian ghi âm)
AUDIO_DURATION = 5   # Thời lượng ghi âm mỗi lần (giây)

# Cấu hình camera
CAMERA_RESOLUTION = (640, 480)  # Độ phân giải camera