# File: config.py
# Cấu hình cho client âm thanh

import os
import argparse

# Xử lý tham số dòng lệnh
parser = argparse.ArgumentParser(description='Baby Monitor Audio Client')
parser.add_argument('--server', type=str, default='localhost',
                    help='Địa chỉ IP của Raspberry Pi server')

# Lấy tất cả các đối số được chuyển cho module này
args, _ = parser.parse_known_args()

# Thông tin kết nối với server
SERVER_HOST = args.server  # Sử dụng giá trị từ tham số hoặc mặc định là localhost
HTTP_PORT = 8000           # Cổng HTTP API
WEBSOCKET_PORT = 8765      # Cổng WebSocket

# Đường dẫn lưu trữ
AUDIO_DIR = "downloaded_audio"  # Thư mục lưu các file âm thanh tải về

# Đảm bảo thư mục AUDIO_DIR tồn tại
os.makedirs(AUDIO_DIR, exist_ok=True)

# Cấu hình phát âm thanh
AUDIO_SAMPLE_RATE = 16000  # Tần số lấy mẫu (Hz)
AUDIO_CHANNELS = 1         # Số kênh âm thanh (1 = mono, 2 = stereo)

# Cấu hình giao diện
GUI_TITLE = "Baby Monitor - Audio Client"
GUI_WIDTH = 800
GUI_HEIGHT = 500
REFRESH_INTERVAL = 2000    # Thời gian làm mới dữ liệu (ms)

# Cấu hình thông báo
NOTIFICATION_TIMEOUT = 5000  # Thời gian hiển thị thông báo (ms)