# Baby-Care-IoT

Hệ thống giám sát trẻ sơ sinh sử dụng Internet of Things (IoT), Raspberry Pi và Firebase.

## Tổng quan

Baby-Care-IoT là một hệ thống giám sát trẻ sơ sinh thông minh, sử dụng Raspberry Pi để thu thập và truyền hình ảnh từ phòng trẻ sơ sinh đến các thiết bị của người giám sát thông qua Firebase. Hệ thống có khả năng:

- Thu thập và truyền hình ảnh thời gian thực
- Tự động đăng ký thiết bị với Firebase Firestore
- Phát hiện các trạng thái của trẻ (khóc, nằm sấp, không đắp chăn)
- Cung cấp URL truy cập công khai thông qua ngrok
- Gửi thông báo khi phát hiện hoạt động bất thường của trẻ

## Cấu trúc dự án

```
Baby-Care-IoT/
├── firebase_device_manager.py  # Module quản lý thiết bị với Firebase
├── video_streaming.py          # Module xử lý và truyền video
├── virtual_camera.py           # Module tạo và quản lý camera ảo
├── setup_ngrok.py              # Module thiết lập ngrok tunnel
└── README.md                   # Tài liệu hướng dẫn
```

## Thư viện sử dụng

Dự án sử dụng các thư viện Python sau:

### Xử lý hình ảnh và video
- **ffmpeg**: Công cụ xử lý video và audio đa nền tảng
- **gstreamer**: Framework đa phương tiện cho phép tạo ứng dụng xử lý âm thanh, video và dữ liệu
- **v4l2loopback**: Module kernel Linux cho phép tạo thiết bị camera ảo

### Kết nối mạng và cloud
- **requests**: Thư viện HTTP đơn giản và hiệu quả
- **python-dotenv**: Thư viện đọc các biến môi trường từ file .env
- **uuid**: Thư viện tạo ID duy nhất cho thiết bị

### Web servers
- **apache2/nginx**: Web server để phục vụ stream video

## Nguyên lý hoạt động

### Kiến trúc tổng thể

Hệ thống Baby-Care-IoT hoạt động theo mô hình kết hợp edge computing và cloud:

1. **Edge** (Raspberry Pi):
   - Thu thập dữ liệu hình ảnh từ camera
   - Xử lý sơ bộ dữ liệu
   - Phát stream video qua HLS
   - Tự động đăng ký thiết bị với Firebase

2. **Cloud** (Firebase):
   - Lưu trữ thông tin thiết bị và cấu hình
   - Theo dõi trạng thái hoạt động của thiết bị
   - Cung cấp API cho ứng dụng di động/web
   - Quản lý xác thực và phân quyền

### Quy trình xử lý

#### Đăng ký thiết bị
1. **Khởi tạo thiết bị**: Tạo UUID duy nhất cho thiết bị Raspberry Pi
2. **Đăng ký với Firebase**: Tạo document trong Firestore với thông tin thiết bị
3. **Cập nhật trạng thái**: Thiết bị tự động cập nhật trạng thái online và URI stream

#### Xử lý video
1. **Thu thập hình ảnh**: Camera thu thập hình ảnh liên tục
2. **Tạo camera ảo**: Sử dụng v4l2loopback để tạo thiết bị camera ảo
3. **Stream video**: Chuyển đổi video thành HLS stream phục vụ qua web server
4. **Cung cấp URL public**: Sử dụng ngrok để tạo URL có thể truy cập từ internet

### Cơ chế kết nối với Firebase

Hệ thống sử dụng Firebase REST API để tương tác với Cloud Firestore:
1. Xác thực với Firebase Authentication để lấy token
2. Sử dụng token để thực hiện các thao tác CRUD với Firestore
3. Tự động cập nhật trạng thái thiết bị khi bắt đầu và kết thúc stream

### Cơ chế stream video với ngrok

1. Web server cục bộ (Apache/Nginx) phục vụ HLS stream
2. Ngrok tạo tunnel đến web server cục bộ
3. URL ngrok được cập nhật lên Firebase để người dùng có thể truy cập
4. Kết nối được duy trì và tự động khởi động lại nếu gặp sự cố

## Yêu cầu hệ thống

- Raspberry Pi 2B Model B 
- USB Camera hoặc Pi Camera
- Kết nối internet
- Tài khoản Firebase
- Tài khoản ngrok

## Cài đặt

### 1. Cài đặt các gói phụ thuộc

```bash
# Cài đặt các thư viện Python cần thiết
sudo pip3 install requests python-dotenv uuid

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

### 2. Thiết lập Firebase

1. Truy cập [Firebase Console](https://console.firebase.google.com/)
2. Tạo dự án mới (hoặc sử dụng dự án hiện có)
3. Thiết lập Cloud Firestore
4. Thiết lập Firebase Authentication với phương thức Email/Password
5. Tạo tài khoản người dùng trong Firebase Authentication
6. Lấy thông tin cấu hình Firebase (API Key, Project ID, etc.)

### 3. Thiết lập ngrok

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

### 4. Cấu hình môi trường

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

## Sử dụng

### Đăng ký thiết bị với Firebase

Để đăng ký thiết bị với Firebase Firestore:

```bash
python3 firebase_device_manager.py
```

### Streaming video và cập nhật trạng thái

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

1. **Đăng ký và quản lý thiết bị**
   - Tạo UUID duy nhất cho mỗi thiết bị Raspberry Pi
   - Quản lý trạng thái hoạt động của thiết bị trên Firestore
   - Cập nhật tự động URI stream khi ngrok URL thay đổi

2. **Thu thập và truyền video**
   - Hỗ trợ USB camera và Pi camera
   - Tạo HLS stream cho truyền video ổn định
   - Tối ưu hóa băng thông và chất lượng hình ảnh

3. **Kết nối mạng**
   - Tạo URL public qua ngrok cho phép truy cập từ bên ngoài mạng cục bộ
   - Tự động kết nối lại khi mất kết nối
   - Hỗ trợ kết nối an toàn

## Cấu hình hệ thống

Các cấu hình chính được lưu trong Cloud Firestore:

- **Ngưỡng phát hiện khóc (cryingThreshold)**: Mức độ nhạy khi phát hiện trẻ khóc
- **Ngưỡng phát hiện không có chăn (noBlanketThreshold)**: Mức độ nhạy khi phát hiện trẻ không đắp chăn
- **Ngưỡng phát hiện nằm sấp (proneThreshold)**: Mức độ nhạy khi phát hiện trẻ nằm sấp
- **Ngưỡng phát hiện nằm nghiêng (sideThreshold)**: Mức độ nhạy khi phát hiện trẻ nằm nghiêng

## Gỡ lỗi

### Các vấn đề thường gặp

- **Camera báo lỗi "device busy"**: Sử dụng lệnh `sudo fuser -k /dev/video0`
- **Không lấy được URL ngrok**: Đảm bảo ngrok đang chạy và có thể truy cập API cục bộ
- **Các lỗi xác thực Firebase**: Kiểm tra thông tin trong file `.env`

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

