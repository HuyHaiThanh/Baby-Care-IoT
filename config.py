# File: config.py
# Cấu hình cho client âm thanh

# Thông tin kết nối với server
SERVER_HOST = "localhost"  # Địa chỉ IP của Raspberry Pi server (thay đổi khi triển khai)
HTTP_PORT = 8000           # Cổng HTTP API
WEBSOCKET_PORT = 8765      # Cổng WebSocket

# Đường dẫn lưu trữ
AUDIO_DIR = "downloaded_audio"  # Thư mục lưu các file âm thanh tải về

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