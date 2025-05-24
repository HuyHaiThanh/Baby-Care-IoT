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

## Thư viện sử dụng

Dự án sử dụng các thư viện Python sau:

### Xử lý âm thanh
- **NumPy (1.19.5)**: Thư viện tính toán số học, được sử dụng để xử lý mảng dữ liệu âm thanh
- **SciPy (1.5.4)**: Thư viện khoa học với các thuật toán xử lý tín hiệu, được sử dụng cho phân tích và lọc tín hiệu âm thanh
- **PyAudio (0.2.11)**: Thư viện cung cấp Python binding cho PortAudio, cho phép ghi và phát âm thanh

### Xử lý hình ảnh
- **Pillow (8.1.0)**: Fork mạnh mẽ của thư viện PIL (Python Imaging Library), dùng để xử lý, nén và lưu trữ hình ảnh
- **picamera (1.13.0)**: Thư viện Python để điều khiển camera module của Raspberry Pi

### Kết nối mạng
- **requests (2.25.1)**: Thư viện HTTP đơn giản và hiệu quả
- **websocket-client (1.2.3)**: Client WebSocket cho Python, xử lý kết nối hai chiều với server

### Tiện ích
- **netifaces (0.10.9)**: Thư viện cung cấp thông tin về giao diện mạng
- **python-dotenv (0.15.0)**: Thư viện đọc các biến môi trường từ file .env

## Nguyên lý hoạt động

### Kiến trúc tổng thể

Hệ thống Baby-Care-IoT hoạt động theo mô hình client-server:

1. **Client** (Raspberry Pi):
   - Thu thập dữ liệu âm thanh và hình ảnh từ các cảm biến
   - Xử lý sơ bộ dữ liệu
   - Truyền dữ liệu đến server qua WebSocket

2. **Server** (Máy chủ trong nhà hoặc đám mây):
   - Tiếp nhận dữ liệu từ client
   - Xử lý và phân tích dữ liệu
   - Gửi thông báo khi phát hiện sự kiện
   - Cung cấp giao diện web cho người dùng

### Quy trình xử lý

#### Xử lý hình ảnh
1. **Thu thập hình ảnh**: Camera chụp ảnh theo chu kỳ định kỳ (mặc định là 1 giây)
2. **Xử lý hình ảnh**: Nén hình ảnh thành định dạng JPEG, điều chỉnh kích thước nếu cần
3. **Mã hóa và truyền**: Mã hóa hình ảnh thành base64 và gửi đến server qua WebSocket
4. **Phân tích trên server**: Server có thể phân tích hình ảnh để phát hiện chuyển động hoặc các sự kiện khác

#### Xử lý âm thanh
1. **Thu âm thanh**: Microphone thu âm thanh liên tục với cơ chế sliding window (mặc định cửa sổ 3 giây, trượt 1 giây)
2. **Voice Activity Detection (VAD)**: Phân tích tín hiệu âm thanh để phát hiện hoạt động giọng nói hoặc âm thanh khác thường
3. **Xử lý và nén**: Dữ liệu âm thanh được xử lý, chuyển đổi thành định dạng phù hợp và nén
4. **Truyền dữ liệu**: Gửi dữ liệu âm thanh đã xử lý đến server qua WebSocket
5. **Phân tích trên server**: Server phân tích âm thanh để phát hiện tiếng khóc hoặc âm thanh bất thường

### Cơ chế Voice Activity Detection (VAD)

Hệ thống sử dụng phương pháp đơn giản để phát hiện hoạt động âm thanh:
1. Tính toán mức năng lượng tín hiệu âm thanh
2. So sánh với ngưỡng cài đặt sẵn
3. Khi năng lượng vượt quá ngưỡng, hệ thống xác định có hoạt động âm thanh
4. Dữ liệu chỉ được gửi đến server khi có hoạt động âm thanh, giúp tiết kiệm băng thông

### Cơ chế kết nối WebSocket

WebSocket cho phép kết nối hai chiều giữa client và server:
1. Client thiết lập kết nối với server
2. Kết nối được duy trì liên tục (khác với HTTP thông thường)
3. Hệ thống sử dụng cơ chế tự động kết nối lại với chiến lược "exponential backoff" khi mất kết nối
4. Server có thể gửi lệnh điều khiển về client (ví dụ: điều chỉnh tham số, bật/tắt tính năng)

## Yêu cầu hệ thống

- Raspberry Pi 2B Model B
- USB Camera
- Microphone
- Python 3.7
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



