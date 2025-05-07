# File: config.py
# Cấu hình cho client Raspberry Pi

import os
import socket

#==============================================================
# CẤU HÌNH KẾT NỐI - CHỈNH SỬA THÔNG SỐ BÊN DƯỚI
#==============================================================

# THAY ĐỔI CÁC ĐỊA CHỈ IP & PORT Ở ĐÂY
# Server hình ảnh - Thay đổi giá trị bên phải dấu = để cập nhật
IMAGE_SERVER_HOST = "192.168.5.50"     # Địa chỉ IP server hình ảnh
IMAGE_SERVER_PORT = 8080              # Port server hình ảnh

# Server âm thanh - Thay đổi giá trị bên phải dấu = để cập nhật
AUDIO_SERVER_HOST = "192.168.5.51"     # Địa chỉ IP server âm thanh
AUDIO_SERVER_PORT = 8000              # Port server âm thanh

# Sử dụng ngrok - Đặt thành True nếu muốn kết nối qua ngrok, False để kết nối trực tiếp qua IP
USE_NGROK_FOR_IMAGE = True           # Sử dụng ngrok cho server hình ảnh
USE_NGROK_FOR_AUDIO = True          # Sử dụng ngrok cho server âm thanh

# URL ngrok (chỉ cần điền nếu USE_NGROK = True)
IMAGE_NGROK_URL = "ab8b-1-53-82-6.ngrok-free.app"
AUDIO_NGROK_URL = "a579-1-53-82-6.ngrok-free.app"

#==============================================================
# PHẦN CẤU HÌNH KHÁC - KHÔNG CẦN THAY ĐỔI
#==============================================================

# Thông tin thiết bị
DEVICE_NAME = "Baby-Monitor-Pi2B"
DEVICE_ID = "3a54299f-37d8-452e-b048-7cb7711fe90f"

# Các thư mục
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
PHOTO_DIR = os.path.join(BASE_DIR, "photos")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")

# Tạo URL cho kết nối HTTP
if USE_NGROK_FOR_IMAGE:
    IMAGE_SERVER_URL = f"https://{IMAGE_NGROK_URL}"
else:
    IMAGE_SERVER_URL = f"http://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}"

if USE_NGROK_FOR_AUDIO:
    AUDIO_SERVER_URL = f"https://{AUDIO_NGROK_URL}"
else:
    AUDIO_SERVER_URL = f"http://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}"

# URL các API endpoint
IMAGE_API_ENDPOINT = f"{IMAGE_SERVER_URL}/api/images"
AUDIO_API_ENDPOINT = f"{AUDIO_SERVER_URL}/api/audio"

# WebSocket endpoints
if USE_NGROK_FOR_IMAGE:
    IMAGE_WS_ENDPOINT = f"wss://{IMAGE_NGROK_URL}/ws"
else:
    IMAGE_WS_ENDPOINT = f"ws://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}/ws"

if USE_NGROK_FOR_AUDIO:
    AUDIO_WS_ENDPOINT = f"wss://{AUDIO_NGROK_URL}/ws"
else:
    AUDIO_WS_ENDPOINT = f"ws://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}/ws"

# Thông số thu thập dữ liệu
PHOTO_INTERVAL = 1  # Khoảng thời gian chụp ảnh (giây)
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

# Tương thích ngược với code hiện tại sử dụng CONNECTION_CONFIG
CONNECTION_CONFIG = {
    "image_server": {
        "use_ngrok": USE_NGROK_FOR_IMAGE,
        "local_host": IMAGE_SERVER_HOST,
        "local_port": IMAGE_SERVER_PORT,
        "ngrok_url": IMAGE_NGROK_URL,
        "use_ssl": USE_NGROK_FOR_IMAGE
    },
    "audio_server": {
        "use_ngrok": USE_NGROK_FOR_AUDIO,
        "local_host": AUDIO_SERVER_HOST,
        "local_port": AUDIO_SERVER_PORT,
        "ngrok_url": AUDIO_NGROK_URL,
        "use_ssl": USE_NGROK_FOR_AUDIO
    }
}

# Các hàm để tương thích với mã nguồn hiện có
def load_connection_config():
    return CONNECTION_CONFIG

def save_connection_config(config):
    # Không cần lưu vào file, chỉ cập nhật biến toàn cục
    global CONNECTION_CONFIG, IMAGE_SERVER_HOST, IMAGE_SERVER_PORT
    global AUDIO_SERVER_HOST, AUDIO_SERVER_PORT, USE_NGROK_FOR_IMAGE, USE_NGROK_FOR_AUDIO
    global IMAGE_NGROK_URL, AUDIO_NGROK_URL, IMAGE_SERVER_URL, AUDIO_SERVER_URL
    global IMAGE_API_ENDPOINT, AUDIO_API_ENDPOINT, IMAGE_WS_ENDPOINT, AUDIO_WS_ENDPOINT
    
    CONNECTION_CONFIG = config
    
    # Cập nhật lại các biến từ cấu hình
    if "image_server" in config:
        USE_NGROK_FOR_IMAGE = config["image_server"]["use_ngrok"]
        IMAGE_SERVER_HOST = config["image_server"]["local_host"]
        IMAGE_SERVER_PORT = config["image_server"]["local_port"]
        IMAGE_NGROK_URL = config["image_server"]["ngrok_url"]
        
    if "audio_server" in config:
        USE_NGROK_FOR_AUDIO = config["audio_server"]["use_ngrok"]
        AUDIO_SERVER_HOST = config["audio_server"]["local_host"]
        AUDIO_SERVER_PORT = config["audio_server"]["local_port"]
        AUDIO_NGROK_URL = config["audio_server"]["ngrok_url"]
    
    # Cập nhật URL
    if USE_NGROK_FOR_IMAGE:
        IMAGE_SERVER_URL = f"https://{IMAGE_NGROK_URL}"
    else:
        IMAGE_SERVER_URL = f"http://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}"

    if USE_NGROK_FOR_AUDIO:
        AUDIO_SERVER_URL = f"https://{AUDIO_NGROK_URL}"
    else:
        AUDIO_SERVER_URL = f"http://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}"
        
    # Cập nhật endpoints
    IMAGE_API_ENDPOINT = f"{IMAGE_SERVER_URL}/api/images"
    AUDIO_API_ENDPOINT = f"{AUDIO_SERVER_URL}/api/audio"
    
    if USE_NGROK_FOR_IMAGE:
        IMAGE_WS_ENDPOINT = f"wss://{IMAGE_NGROK_URL}/ws"
    else:
        IMAGE_WS_ENDPOINT = f"ws://{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}/ws"

    if USE_NGROK_FOR_AUDIO:
        AUDIO_WS_ENDPOINT = f"wss://{AUDIO_NGROK_URL}/ws"
    else:
        AUDIO_WS_ENDPOINT = f"ws://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}/ws"
    
    return True

def get_server_url(server_type):
    if server_type == "image":
        return IMAGE_SERVER_URL
    else:
        return AUDIO_SERVER_URL

def get_ws_url(server_type):
    if server_type == "image":
        return IMAGE_WS_ENDPOINT
    else:
        return AUDIO_WS_ENDPOINT