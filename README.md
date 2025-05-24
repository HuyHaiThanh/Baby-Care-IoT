# Baby-Care-IoT

Hệ thống giám sát trẻ sơ sinh sử dụng Internet of Things (IoT) và Raspberry Pi.

## Tổng quan

Baby-Care-IoT là một hệ thống giám sát trẻ sơ sinh thông minh, sử dụng Raspberry Pi để thu thập và truyền âm thanh và hình ảnh từ phòng trẻ sơ sinh đến các thiết bị của người giám sát. Hệ thống có khả năng:

- Thu thập và truyền hình ảnh thời gian thực
- Thu thập và truyền âm thanh (hỗ trợ Voice Activity Detection)
- Kết nối với máy chủ qua WebSocket
- Gửi thông báo khi phát hiện hoạt động của trẻ

## Cấu trúc dự án

```
Baby-Care-IoT/
├── audio_client.py     # Module xử lý âm thanh
├── camera_client.py    # Module xử lý hình ảnh
├── config.py           # Cấu hình hệ thống
├── main.py             # File chính để chạy ứng dụng
├── requirements.txt    # Các thư viện cần thiết
├── utils.py            # Các tiện ích
└── websocket_client.py # Module kết nối WebSocket
```

## Yêu cầu hệ thống

- Raspberry Pi (khuyến nghị Pi 3B+ hoặc cao hơn)
- Camera (Pi Camera hoặc USB Camera)
- Microphone
- Python 3.7 hoặc cao hơn
- Kết nối internet

## Cài đặt

1. Clone repository:
   ```
   git clone <repository-url>
   cd Baby-Care-IoT
   ```

2. Cài đặt các thư viện:
   ```
   pip install -r requirements.txt
   ```

3. Cấu hình hệ thống:
   Chỉnh sửa file `config.py` để cập nhật các thông số như địa chỉ máy chủ, cổng kết nối, và các thiết lập khác.

## Sử dụng

Chạy ứng dụng:

```
python main.py
```

Các tùy chọn:

- `--camera-mode`: Chỉ chạy chế độ truyền hình ảnh
- `--audio-mode`: Chỉ chạy chế độ truyền âm thanh
- `--no-vad`: Tắt chức năng Voice Activity Detection (VAD)
- `--simple-display`: Sử dụng chế độ hiển thị đơn giản (tương thích tốt hơn)
- `--debug`: Hiển thị thông tin log và chi tiết lỗi
- `--image-server`: Địa chỉ server hình ảnh (IP:port hoặc hostname:port)

## Chức năng chính

1. **Thu thập hình ảnh**
   - Hỗ trợ PiCamera và USB camera
   - Chụp ảnh theo khoảng thời gian cài đặt
   - Gửi ảnh đến máy chủ qua WebSocket

2. **Thu thập âm thanh**
   - Thu âm thanh liên tục với khung trượt (sliding window)
   - Phát hiện hoạt động giọng nói (Voice Activity Detection)
   - Gửi âm thanh đến máy chủ qua WebSocket

3. **Kết nối mạng**
   - Hỗ trợ kết nối trực tiếp qua IP hoặc qua ngrok
   - Tự động kết nối lại khi mất kết nối
   - Hỗ trợ kết nối an toàn

## Cấu hình hệ thống

Các cấu hình chính có thể được đặt trong file `config.py`:

- Địa chỉ máy chủ hình ảnh và âm thanh
- Cổng kết nối
- Cấu hình cho ngrok tunnel
- Thông tin thiết bị
- Cấu hình Voice Activity Detection (VAD)

## Gỡ lỗi

Các log file được lưu trong thư mục `logs/`:
- `babycare.log`: Log chung của ứng dụng
- `error.log`: Log các lỗi

Để xem thông tin debug chi tiết, chạy ứng dụng với tham số `--debug`.

