# File: config.py
# Cấu hình cho client Raspberry Pi

import os
import socket
import json

# Thông tin thiết bị
DEVICE_NAME = "Baby-Monitor-Pi2B"
DEVICE_ID = "c17ca988-1877-4b72-a5ed-47beee86f2ae"  # ID định danh thiết bị

# Các thư mục
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
PHOTO_DIR = os.path.join(BASE_DIR, "photos")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")
CONFIG_FILE = os.path.join(BASE_DIR, "connection_config.json")

# Mặc định cấu hình kết nối
DEFAULT_CONNECTION_CONFIG = {
    "image_server": {
        "use_ngrok": False,
        "local_host": "192.168.5.50",
        "local_port": 8080,
        "ngrok_url": "6a89-2405-4802-69ca-f090-65ae-8855-368a-9353.ngrok-free.app",
        "use_ssl": False
    },
    "audio_server": {
        "use_ngrok": True,
        "local_host": "192.168.5.51",
        "local_port": 8000,
        "ngrok_url": "759e-42-112-80-76.ngrok-free.app",
        "use_ssl": True
    }
}

# Đọc cấu hình từ file nếu tồn tại, nếu không sử dụng mặc định
def load_connection_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Lỗi khi đọc file config: {e}")
            return DEFAULT_CONNECTION_CONFIG
    else:
        # Lưu cấu hình mặc định nếu file không tồn tại
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(DEFAULT_CONNECTION_CONFIG, f, indent=4)
        except Exception as e:
            print(f"Lỗi khi tạo file config: {e}")
        return DEFAULT_CONNECTION_CONFIG

# Lưu cấu hình kết nối vào file
def save_connection_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Lỗi khi lưu file config: {e}")
        return False

# Tải cấu hình
CONNECTION_CONFIG = load_connection_config()

# Hàm để tạo URL dựa trên loại kết nối
def get_server_url(server_type, protocol="http"):
    config = CONNECTION_CONFIG[f"{server_type}_server"]
    
    if config["use_ngrok"]:
        # Sử dụng ngrok URL
        if not config["ngrok_url"]:
            print(f"CẢNH BÁO: Không có ngrok URL cho {server_type}_server, sử dụng local URL")
            url_prefix = "https://" if config["use_ssl"] else "http://"
            return f"{url_prefix}{config['local_host']}:{config['local_port']}"
        else:
            url_prefix = "https://" if config["use_ssl"] else "http://"
            return f"{url_prefix}{config['ngrok_url']}"
    else:
        # Sử dụng địa chỉ IP local
        url_prefix = "https://" if config["use_ssl"] else "http://"
        return f"{url_prefix}{config['local_host']}:{config['local_port']}"

def get_ws_url(server_type):
    config = CONNECTION_CONFIG[f"{server_type}_server"]
    
    if config["use_ngrok"]:
        # Sử dụng ngrok URL với WebSocket
        if not config["ngrok_url"]:
            print(f"CẢNH BÁO: Không có ngrok URL cho {server_type}_server, sử dụng local URL")
            ws_prefix = "wss://" if config["use_ssl"] else "ws://"
            return f"{ws_prefix}{config['local_host']}:{config['local_port']}/ws"
        else:
            ws_prefix = "wss://" if config["use_ssl"] else "ws://"
            return f"{ws_prefix}{config['ngrok_url']}/ws"
    else:
        # Sử dụng địa chỉ IP local với WebSocket
        ws_prefix = "wss://" if config["use_ssl"] else "ws://"
        return f"{ws_prefix}{config['local_host']}:{config['local_port']}/ws"

# Thông số server - sử dụng cấu hình linh hoạt
IMAGE_SERVER_URL = get_server_url("image")
AUDIO_SERVER_URL = get_server_url("audio")

# Phân tích URL để lấy thông tin host và port
def parse_server_url(url):
    if "://" in url:
        url_without_protocol = url.split("://")[1]
        if ":" in url_without_protocol and "/" not in url_without_protocol.split(":")[0]:
            # URL có dạng protocol://host:port/path
            host = url_without_protocol.split(":")[0]
            port = int(url_without_protocol.split(":")[1].split("/")[0])
        else:
            # URL có dạng protocol://host/path
            host = url_without_protocol.split("/")[0]
            port = 443 if url.startswith("https") else 80
    else:
        host = url
        port = 80
    return host, port

# Lấy thông tin host và port từ URL
IMAGE_SERVER_HOST, IMAGE_SERVER_PORT = parse_server_url(IMAGE_SERVER_URL)
AUDIO_SERVER_HOST, AUDIO_SERVER_PORT = parse_server_url(AUDIO_SERVER_URL)

# URL các API endpoint
IMAGE_API_ENDPOINT = f"{IMAGE_SERVER_URL}/api/images"
AUDIO_API_ENDPOINT = f"{AUDIO_SERVER_URL}/api/audio"
IMAGE_WS_ENDPOINT = get_ws_url("image")
AUDIO_WS_ENDPOINT = get_ws_url("audio")

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