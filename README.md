# Baby Care IoT với Raspberry Pi 2B

Dự án IoT sử dụng Raspberry Pi 2B, Firebase Firestore, và ngrok để xây dựng hệ thống giám sát trẻ em.

## Mô tả dự án

Dự án này gồm hai phần chức năng chính:

1. **Đăng ký thiết bị với Firebase Firestore**: Tự động đăng ký thiết bị vào Firestore khi khởi động với UUID duy nhất.
2. **Quản lý video streaming**: Xử lý stream video từ camera và cập nhật trạng thái lên Firebase.

## Yêu cầu hệ thống

- Raspberry Pi 2B (hoặc mới hơn)
- Camera USB hoặc Pi Camera
- Kết nối Internet
- Dự án Firebase với Cloud Firestore đã được thiết lập
- ngrok (để cung cấp URL public cho streaming)

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

## Cách sử dụng

### Đăng ký thiết bị với Firebase

Khi thiết bị khởi động lần đầu, chạy script `firebase_device_manager.py` để đăng ký thiết bị:

```bash
python3 firebase_device_manager.py
```

Script này sẽ:
- Tạo UUID duy nhất cho thiết bị và lưu vào file `device_uuid.json`
- Kiểm tra xem thiết bị đã được đăng ký trong collection `devices` chưa
- Nếu chưa, tạo document mới với các giá trị mặc định
- Nếu đã tồn tại, chỉ cập nhật URI và updatedAt

### Streaming video và cập nhật trạng thái

Để bắt đầu streaming video:

1. Khởi động ngrok để tạo tunnel:
```bash
ngrok http 80
```

2. Chạy script streaming:
```bash
python3 video_streaming.py
```

Script sẽ:
- Khởi tạo thiết bị trên Firebase (nếu chưa đăng ký)
- Cập nhật URI mới từ ngrok
- Đổi trạng thái `isOnline` thành `true`
- Khi tắt stream, tự động cập nhật trạng thái `isOnline` thành `false`

## Giải thích chi tiết

### File `firebase_device_manager.py`

File này chứa các chức năng chính để tương tác với Firebase Firestore:

1. **get_device_uuid()**: Lấy hoặc tạo UUID cho thiết bị
2. **get_ngrok_url()**: Lấy URL public từ ngrok
3. **authenticate_firebase()**: Xác thực với Firebase Authentication 
4. **check_device_exists()**: Kiểm tra thiết bị đã tồn tại trong Firestore chưa
5. **register_device()**: Đăng ký thiết bị mới hoặc cập nhật thiết bị hiện có
6. **update_streaming_status()**: Cập nhật trạng thái và URI streaming
7. **initialize_device()**: Khởi tạo thiết bị khi khởi động

### File `video_streaming.py`

File này quản lý quá trình streaming video và tích hợp với Firebase:

1. Tạo thiết bị ảo thông qua v4l2loopback
2. Sao chép luồng video từ camera thật sang thiết bị ảo
3. Tạo HLS stream với GStreamer
4. Khi bắt đầu stream, tự động cập nhật `isOnline = true` và URI
5. Khi kết thúc stream, tự động cập nhật `isOnline = false`

## Cấu trúc Dữ liệu trên Firestore

Trong collection `devices`, mỗi thiết bị sẽ có document với ID là UUID của thiết bị và các field:

- **id**: UUID của thiết bị (string)
- **createdAt**: Thời gian tạo thiết bị (timestamp)
- **updatedAt**: Thời gian cập nhật cuối (timestamp)
- **cryingThreshold**: Ngưỡng phát hiện khóc (mặc định 60) (number)
- **noBlanketThreshold**: Ngưỡng phát hiện không có chăn (mặc định 60) (number)
- **proneThreshold**: Ngưỡng phát hiện nằm sấp (mặc định 30) (number)
- **sideThreshold**: Ngưỡng phát hiện nằm nghiêng (mặc định 30) (number)
- **isOnline**: Trạng thái streaming (boolean)
- **uri**: URL ngrok để truy cập stream (string)

## Lưu ý

- Đảm bảo file `.env` chứa thông tin xác thực chính xác
- URI sẽ tự động cập nhật khi ngrok URI thay đổi 
- Thiết bị cần có quyền truy cập vào camera
- Đảm bảo ngrok đang chạy trước khi bắt đầu streaming
- Sử dụng phương thức REST API thay vì Pyrebase để tiết kiệm tài nguyên

## Xử lý sự cố

- Nếu camera báo lỗi "device busy": `sudo fuser -k /dev/video0`
- Nếu không lấy được URL ngrok: Đảm bảo ngrok đang chạy và truy cập được API cục bộ
- Các lỗi xác thực: Kiểm tra thông tin trong file `.env`

## Tài nguyên tham khảo

- [Firebase REST API Documentation](https://firebase.google.com/docs/reference/rest/database)
- [Cloud Firestore REST API](https://firebase.google.com/docs/firestore/use-rest-api)
- [ngrok Documentation](https://ngrok.com/docs)
- [v4l2loopback Documentation](https://github.com/umlaeute/v4l2loopback)