# File: config.py
# Cấu hình cho client Raspberry Pi

import os
import socket

# Thông tin thiết bị
DEVICE_NAME = "Baby-Monitor-Pi2B"
DEVICE_ID = "c17ca988-1877-4b72-a5ed-47beee86f2ae"  # ID định danh thiết bị

# Các thư mục
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
PHOTO_DIR = os.path.join(BASE_DIR, "photos")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")

# Thông số server
IMAGE_SERVER_HOST = "192.168.5.50"  # Địa chỉ server xử lý hình ảnh
IMAGE_SERVER_PORT = 8080              # Port server xử lý hình ảnh
AUDIO_SERVER_HOST = "192.168.1.101"  # Địa chỉ server xử lý âm thanh
AUDIO_SERVER_PORT = 8001              # Port server xử lý âm thanh

# URL cho kết nối HTTP
IMAGE_SERVER_URL = f"http://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}"
AUDIO_SERVER_URL = f"http://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}"

# URL các API endpoint
IMAGE_API_ENDPOINT = f"{IMAGE_SERVER_URL}/api/images"
AUDIO_API_ENDPOINT = f"{AUDIO_SERVER_URL}/api/audio"
IMAGE_WS_ENDPOINT = f"ws://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}/ws"
AUDIO_WS_ENDPOINT = f"ws://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}/ws"

# Thông số thu thập dữ liệu
PHOTO_INTERVAL = 5  # Khoảng thời gian chụp ảnh (giây)
AUDIO_DURATION = 3  # Độ dài của mỗi đoạn ghi âm (giây)
AUDIO_SLIDE_SIZE = 1  # Độ dịch chuyển cửa sổ ghi âm (giây)
SAMPLE_RATE = 16000  # Tần số lấy mẫu âm thanh (Hz)
CHANNELS = 1  # Kênh âm thanh (1 = mono)

# Cài đặt kết nối
MAX_RETRIES = 5  # Số lần thử lại kết nối tối đa
RETRY_DELAY = 3  # Thời gian chờ giữa các lần thử lại (giây)
CONNECTION_TIMEOUT = 10  # Thời gian timeout cho các yêu cầu (giây)
RECONNECT_INTERVAL = 5  # Thời gian chờ trước khi thử kết nối lại (giây)

# Cấu hình cho chế độ debug
DEBUG = True  # Chế độ debug, hiển thị nhiều thông tin hơn

# Tạo các thư mục nếu chưa tồn tại
for directory in [TEMP_DIR, PHOTO_DIR, AUDIO_DIR, ARCHIVE_DIR]:
    os.makedirs(directory, exist_ok=True)