# Baby-Care-IoT

Hệ thống giám sát trẻ sơ sinh sử dụng Internet of Things (IoT), Raspberry Pi và các công nghệ streaming hiện đại.

## Tổng quan

Baby-Care-IoT là một hệ thống giám sát trẻ sơ sinh thông minh, sử dụng Raspberry Pi để thu thập và truyền âm thanh và hình ảnh từ phòng trẻ sơ sinh đến các thiết bị của người giám sát. Hệ thống có khả năng:

- Thu thập và truyền hình ảnh thời gian thực
- Thu thập và truyền âm thanh (hỗ trợ Voice Activity Detection)
- Kết nối với máy chủ qua WebSocket
- Tự động đăng ký thiết bị với Firebase Firestore
- Phát hiện các trạng thái của trẻ (khóc, nằm sấp, không đắp chăn)
- Cung cấp URL truy cập công khai thông qua ngrok
- Gửi thông báo khi phát hiện hoạt động bất thường của trẻ

## Cấu trúc dự án

```
Baby-Care-IoT/
├── main.py                     # File chính để chạy ứng dụng
├── requirements.txt            # Các thư viện cần thiết
├── README.md                   # Tài liệu hướng dẫn
├── backup_original_files/      # Backup các file gốc trước khi refactor
└── src/                        # Source code chính được tổ chức theo module
    ├── __init__.py             # Package exports chính
    ├── clients/                # Clients cho xử lý âm thanh và hình ảnh
    │   ├── __init__.py
    │   ├── audio_client.py     # Module xử lý âm thanh
    │   ├── camera_client.py    # Module xử lý hình ảnh
    │   └── base_client.py      # Base class cho các client
    ├── core/                   # Core configuration và settings
    │   ├── __init__.py
    │   └── config.py           # Cấu hình hệ thống
    ├── network/                # Network communication modules
    │   ├── __init__.py
    │   └── websocket_client.py # Module kết nối WebSocket
    ├── services/               # External services integration
    │   ├── __init__.py
    │   └── firebase_device_manager.py # Module quản lý thiết bị với Firebase
    ├── streaming/              # Video streaming và tunneling
    │   ├── __init__.py
    │   ├── video_streaming.py  # Module xử lý và truyền video
    │   ├── virtual_camera.py   # Module tạo và quản lý camera ảo
    │   └── setup_ngrok.py      # Module thiết lập ngrok tunnel
    └── utils/                  # Utility functions và helpers
        ├── __init__.py
        ├── logger.py           # Logging configuration
        └── helpers.py          # Various utility functions
```

## Kiến trúc mã nguồn

### Tổ chức modular
Dự án được tổ chức theo kiến trúc modular để dễ bảo trì và mở rộng:

- **`src/clients/`**: Chứa các client class xử lý các loại dữ liệu khác nhau
  - `AudioRecorder`: Ghi âm và truyền âm thanh với sliding window và VAD
  - `CameraClient`: Chụp và truyền hình ảnh
  - `BaseClient`: Class cơ sở cho các client khác

- **`src/core/`**: Cấu hình và settings cốt lõi
  - `config.py`: Toàn bộ cấu hình hệ thống, server endpoints, device settings

- **`src/network/`**: Modules xử lý kết nối mạng
  - `WebSocketClient`: Client WebSocket với auto-reconnect và heartbeat

- **`src/services/`**: Tích hợp với các dịch vụ bên ngoài
  - `FirebaseDeviceManager`: Quản lý đăng ký thiết bị và trạng thái với Firebase Firestore

- **`src/streaming/`**: Xử lý video streaming và tunneling
  - `VideoStreaming`: HLS video streaming với GStreamer
  - `VirtualCamera`: Tạo và quản lý camera ảo với v4l2loopback
  - `NgrokSetup`: Thiết lập public tunnel qua ngrok

- **`src/utils/`**: Utility functions và helpers
  - `logger.py`: Cấu hình logging với multiple handlers
  - `helpers.py`: Device info, network utilities

### Lợi ích của kiến trúc modular
1. **Separation of Concerns**: Mỗi module có trách nhiệm rõ ràng
2. **Reusability**: Các module có thể tái sử dụng trong các project khác
3. **Maintainability**: Dễ dàng bảo trì và debug từng phần riêng biệt
4. **Scalability**: Dễ mở rộng với các tính năng mới
5. **Testing**: Có thể test từng module độc lập

## Thư viện sử dụng

Dự án sử dụng các thư viện Python sau:

### Xử lý âm thanh
- **NumPy (1.19.5)**: Thư viện tính toán số học, được sử dụng để xử lý mảng dữ liệu âm thanh
- **SciPy (1.5.4)**: Thư viện khoa học với các thuật toán xử lý tín hiệu, được sử dụng cho phân tích và lọc tín hiệu âm thanh
- **PyAudio (0.2.11)**: Thư viện cung cấp Python binding cho PortAudio, cho phép ghi và phát âm thanh

### Xử lý hình ảnh và video
- **Pillow (8.1.0)**: Fork mạnh mẽ của thư viện PIL (Python Imaging Library), dùng để xử lý, nén và lưu trữ hình ảnh
- **picamera (1.13.0)**: Thư viện Python để điều khiển camera module của Raspberry Pi
- **ffmpeg**: Công cụ xử lý video và audio đa nền tảng
- **gstreamer**: Framework đa phương tiện cho phép tạo ứng dụng xử lý âm thanh, video và dữ liệu
- **v4l2loopback**: Module kernel Linux cho phép tạo thiết bị camera ảo

### Kết nối mạng và cloud
- **requests (2.25.1)**: Thư viện HTTP đơn giản và hiệu quả
- **websocket-client (1.2.3)**: Client WebSocket cho Python, xử lý kết nối hai chiều với server
- **python-dotenv**: Thư viện đọc các biến môi trường từ file .env

### Tiện ích
- **netifaces (0.10.9)**: Thư viện cung cấp thông tin về giao diện mạng
- **uuid**: Thư viện tạo ID duy nhất cho thiết bị

### Web servers
- **apache2/nginx**: Web server để phục vụ stream video

## Nguyên lý hoạt động

### Kiến trúc tổng thể

Hệ thống Baby-Care-IoT hoạt động theo mô hình kết hợp edge computing, client-server và cloud:

1. **Edge** (Raspberry Pi):
   - Thu thập dữ liệu âm thanh và hình ảnh từ các cảm biến
   - Xử lý sơ bộ dữ liệu
   - Phát stream video qua HLS
   - Truyền dữ liệu đến server qua WebSocket
   - Tự động đăng ký thiết bị với Firebase

2. **Server** (Máy chủ trong nhà hoặc đám mây):
   - Tiếp nhận dữ liệu từ client
   - Xử lý và phân tích dữ liệu
   - Gửi thông báo khi phát hiện sự kiện
   - Cung cấp giao diện web cho người dùng

3. **Cloud** (Firebase):
   - Lưu trữ thông tin thiết bị và cấu hình
   - Theo dõi trạng thái hoạt động của thiết bị
   - Cung cấp API cho ứng dụng di động/web
   - Quản lý xác thực và phân quyền

### Quy trình xử lý

#### Đăng ký thiết bị
1. **Khởi tạo thiết bị**: Tạo UUID duy nhất cho thiết bị Raspberry Pi
2. **Đăng ký với Firebase**: Tạo document trong Firestore với thông tin thiết bị
3. **Cập nhật trạng thái**: Thiết bị tự động cập nhật trạng thái online và URI stream

#### Xử lý hình ảnh
1. **Thu thập hình ảnh**: Camera chụp ảnh theo chu kỳ định kỳ (mặc định là 1 giây)
2. **Tạo camera ảo**: Sử dụng v4l2loopback để tạo thiết bị camera ảo
3. **Stream video**: Chuyển đổi video thành HLS stream phục vụ qua web server
4. **Xử lý hình ảnh**: Nén hình ảnh thành định dạng JPEG, điều chỉnh kích thước nếu cần
5. **Mã hóa và truyền**: Mã hóa hình ảnh thành base64 và gửi đến server qua WebSocket
6. **Cung cấp URL public**: Sử dụng ngrok để tạo URL có thể truy cập từ internet
7. **Phân tích trên server**: Server có thể phân tích hình ảnh để phát hiện chuyển động hoặc các sự kiện khác

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

### Cơ chế kết nối với Firebase

Hệ thống sử dụng Firebase REST API để tương tác với Cloud Firestore:
1. Xác thực với Firebase Authentication để lấy token
2. Sử dụng token để thực hiện các thao tác CRUD với Firestore
3. Tự động cập nhật trạng thái thiết bị khi bắt đầu và kết thúc stream

### Cơ chế kết nối WebSocket

WebSocket cho phép kết nối hai chiều giữa client và server:
1. Client thiết lập kết nối với server
2. Kết nối được duy trì liên tục (khác với HTTP thông thường)
3. Hệ thống sử dụng cơ chế tự động kết nối lại với chiến lược "exponential backoff" khi mất kết nối
4. Server có thể gửi lệnh điều khiển về client (ví dụ: điều chỉnh tham số, bật/tắt tính năng)

### Cơ chế stream video với ngrok

1. Web server cục bộ (Apache/Nginx) phục vụ HLS stream
2. Ngrok tạo tunnel đến web server cục bộ
3. URL ngrok được cập nhật lên Firebase để người dùng có thể truy cập
4. Kết nối được duy trì và tự động khởi động lại nếu gặp sự cố

## Yêu cầu hệ thống

- Raspberry Pi 2B Model B 
- USB Camera hoặc Pi Camera
- Microphone
- Kết nối internet
- Python 3.7+
- Tài khoản Firebase
- Tài khoản ngrok

## Cài đặt

### 1. Clone repository và cài đặt thư viện

```bash
# Clone repository
git clone <repository-url>
cd Baby-Care-IoT

# Cài đặt các thư viện Python cần thiết
pip install -r requirements.txt

# Hoặc cài đặt thủ công
sudo pip3 install requests python-dotenv uuid numpy scipy pyaudio pillow websocket-client netifaces
```

### 2. Cài đặt các gói hệ thống

```bash
# Cài đặt v4l2loopback để tạo thiết bị camera ảo
sudo apt-get update
sudo apt-get install -y v4l2loopback-dkms v4l2loopback-utils

# Cài đặt ffmpeg và gstreamer cho streaming
sudo apt-get install -y ffmpeg gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly

# Cài đặt web server (Apache hoặc Nginx)
sudo apt-get install -y apache2
# HOẶC
sudo apt-get install -y nginx
```

### 3. Thiết lập Firebase

1. Truy cập [Firebase Console](https://console.firebase.google.com/)
2. Tạo dự án mới (hoặc sử dụng dự án hiện có)
3. Thiết lập Cloud Firestore
4. Thiết lập Firebase Authentication với phương thức Email/Password
5. Tạo tài khoản người dùng trong Firebase Authentication
6. Lấy thông tin cấu hình Firebase (API Key, Project ID, etc.)

### 4. Thiết lập ngrok

1. Đăng ký tài khoản tại [ngrok.com](https://ngrok.com/)
2. Tải và cài đặt ngrok:
```bash
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
sudo tar xvzf ngrok-v3-stable-linux-arm.tgz -C /usr/local/bin
```

3. Xác thực ngrok với token của bạn:
```bash
ngrok authtoken YOUR_AUTHTOKEN_HERE
```

### 5. Cấu hình môi trường

1. Tạo file `.env` trong thư mục dự án:
```bash
nano .env
```

2. Thêm các thông tin sau vào file:
```
API_KEY=YOUR_FIREBASE_API_KEY
EMAIL=YOUR_FIREBASE_AUTH_EMAIL
PASSWORD=YOUR_FIREBASE_AUTH_PASSWORD
PROJECT_ID=YOUR_FIREBASE_PROJECT_ID
```

3. Cấu hình hệ thống:
   Chỉnh sửa file `config.py` để cập nhật các thông số như địa chỉ máy chủ, cổng kết nối, và các thiết lập khác.

## Sử dụng

### Chế độ client-server (Chính)

Chạy ứng dụng client:

```bash
python main.py
```

Các tùy chọn:

- `--camera-mode`: Chỉ chạy chế độ truyền hình ảnh
- `--audio-mode`: Chỉ chạy chế độ truyền âm thanh
- `--no-vad`: Tắt chức năng Voice Activity Detection (VAD)
- `--simple-display`: Sử dụng chế độ hiển thị đơn giản (tương thích tốt hơn)
- `--debug`: Hiển thị thông tin log và chi tiết lỗi
- `--image-server`: Địa chỉ server hình ảnh (IP:port hoặc hostname:port)
- `--camera-device`: Chỉ định thiết bị camera cụ thể (ví dụ: `/dev/video17`)

Ví dụ để sử dụng camera `/dev/video17`:

```bash
python main.py --camera-device /dev/video17
```

### Chế độ streaming Firebase

#### Đăng ký thiết bị với Firebase

Để đăng ký thiết bị với Firebase Firestore:

```bash
python3 firebase_device_manager.py
```

#### Streaming video và cập nhật trạng thái

Để bắt đầu streaming video:

1. Khởi động ngrok để tạo tunnel:
```bash
python3 setup_ngrok.py
```

2. Chạy script streaming:
```bash
python3 video_streaming.py
```

## Chức năng chính

1. **Thu thập hình ảnh**
   - Hỗ trợ PiCamera và USB camera
   - Chụp ảnh theo khoảng thời gian cài đặt
   - Tạo HLS stream cho truyền video ổn định
   - Gửi ảnh đến máy chủ qua WebSocket

2. **Thu thập âm thanh**
   - Thu âm thanh liên tục với khung trượt (sliding window)
   - Phát hiện hoạt động giọng nói (Voice Activity Detection)
   - Gửi âm thanh đến máy chủ qua WebSocket

3. **Đăng ký và quản lý thiết bị**
   - Tạo UUID duy nhất cho mỗi thiết bị Raspberry Pi
   - Quản lý trạng thái hoạt động của thiết bị trên Firestore
   - Cập nhật tự động URI stream khi ngrok URL thay đổi

4. **Kết nối mạng**
   - Hỗ trợ kết nối trực tiếp qua IP hoặc qua ngrok
   - Tự động kết nối lại khi mất kết nối
   - Hỗ trợ kết nối an toàn
   - Tạo URL public qua ngrok cho phép truy cập từ bên ngoài mạng cục bộ

## Cấu hình hệ thống

### Cấu hình Firebase

Các cấu hình chính được lưu trong Cloud Firestore:

- **Ngưỡng phát hiện khóc (cryingThreshold)**: Mức độ nhạy khi phát hiện trẻ khóc
- **Ngưỡng phát hiện không có chăn (noBlanketThreshold)**: Mức độ nhạy khi phát hiện trẻ không đắp chăn
- **Ngưỡng phát hiện nằm sấp (proneThreshold)**: Mức độ nhạy khi phát hiện trẻ nằm sấp
- **Ngưỡng phát hiện nằm nghiêng (sideThreshold)**: Mức độ nhạy khi phát hiện trẻ nằm nghiêng

### Cấu hình Client

Các cấu hình chính có thể được đặt trong file `config.py`:

- Địa chỉ máy chủ hình ảnh và âm thanh
- Cổng kết nối
- Cấu hình cho ngrok tunnel
- Thông tin thiết bị
- Cấu hình Voice Activity Detection (VAD)

## Gỡ lỗi

### Các vấn đề thường gặp

- **Camera báo lỗi "device busy"**: Sử dụng lệnh `sudo fuser -k /dev/video0`
- **Không lấy được URL ngrok**: Đảm bảo ngrok đang chạy và có thể truy cập API cục bộ
- **Các lỗi xác thực Firebase**: Kiểm tra thông tin trong file `.env`

### Log files

Các log file được lưu trong thư mục `logs/`:
- `babycare.log`: Log chung của ứng dụng
- `error.log`: Log các lỗi

Để xem thông tin debug chi tiết, chạy ứng dụng với tham số `--debug`.

## Phụ lục

### Cấu trúc dữ liệu trên Firestore

Trong collection `devices`, mỗi thiết bị sẽ có document với ID là UUID của thiết bị và các field:

```json
{
  "id": "18ff6551-820b-4aad-b714-1143629970f0",
  "createdAt": "2023-05-24T10:15:30.123Z",
  "updatedAt": "2023-05-24T10:20:45.789Z",
  "cryingThreshold": 60,
  "noBlanketThreshold": 60,
  "proneThreshold": 30,
  "sideThreshold": 30,
  "isOnline": true,
  "uri": "https://ec35-1-53-82-6.ngrok-free.app"
}
```

