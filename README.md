# Baby Care IoT với Raspberry Pi 2B và Cloud Firestore

Dự án này bao gồm hai phần chính: (1) đăng ký thiết bị với Firebase Cloud Firestore và (2) xử lý streaming video từ camera để giải quyết vấn đề xung đột truy cập giữa nhiều ứng dụng.

## Yêu Cầu Hệ Thống

- Raspberry Pi 2B với hệ điều hành Raspbian/Raspberry Pi OS
- Python 3.6 hoặc cao hơn
- Camera USB hoặc Pi Camera
- Tài khoản Firebase (đã kích hoạt Cloud Firestore)
- Kết nối internet

## Cài Đặt

### 1. Cài đặt các gói phụ thuộc

```bash
# Cài đặt các thư viện Python cần thiết
sudo pip3 install requests uuid

# Cài đặt v4l2loopback để tạo thiết bị camera ảo
sudo apt-get update
sudo apt-get install -y v4l2loopback-dkms v4l2loopback-utils

# Cài đặt ffmpeg và gstreamer để streaming
sudo apt-get install -y ffmpeg gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly

# Cài đặt web server (nếu chưa có)
sudo apt-get install -y nginx
```

### 2. Cấu hình Nginx (Web Server)

```bash
# Tạo thư mục để lưu trữ video stream
sudo mkdir -p /var/www/html
sudo chown -R pi:pi /var/www/html  # Thay 'pi' bằng username của bạn

# Đảm bảo Nginx được cấu hình để phục vụ thư mục này
sudo nano /etc/nginx/sites-available/default
```

Điều chỉnh file cấu hình Nginx để thêm cấu hình CORS:

```
server {
    # ... Cấu hình mặc định ...
    
    location / {
        # ... Cấu hình mặc định ...
        
        # Thêm header CORS
        add_header 'Access-Control-Allow-Origin' '*';
        add_header 'Access-Control-Allow-Methods' 'GET, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';
    }
}
```

Sau đó khởi động lại Nginx:

```bash
sudo systemctl restart nginx
```

## Thiết Lập Firebase

### 1. Tạo Project Firebase

1. Truy cập [Firebase Console](https://console.firebase.google.com/)
2. Nhấp vào "Add Project" và làm theo các bước để tạo dự án mới
3. Kích hoạt Cloud Firestore: vào Database > Create Database > Bắt đầu ở chế độ production

### 2. Thiết lập Xác thực Firebase

1. Trong Firebase Console, vào "Authentication" > "Sign-in method"
2. Kích hoạt phương thức "Email/Password"
3. Tạo người dùng với email và mật khẩu trong tab "Users"

### 3. Lấy Thông Tin Kết Nối Firebase

1. Trong Firebase Console, vào "Project settings" (biểu tượng bánh răng)
2. Trong tab "General", cuộn xuống phần "Your apps"
3. Nhấp vào biểu tượng web (</>) để thêm ứng dụng web
4. Đặt tên cho ứng dụng và nhấp "Register app"
5. Sao chép thông tin sau:
   - `apiKey` - Dùng làm `API_KEY` trong script đăng ký thiết bị
   - `projectId` - Dùng làm `PROJECT_ID` trong script đăng ký thiết bị

## Cách Sử Dụng

### 1. Đăng ký thiết bị với Firebase

1. Chỉnh sửa file `device_registration.py`:
   - Cập nhật `API_KEY` bằng API key của Firebase
   - Cập nhật `EMAIL` và `PASSWORD` với thông tin đăng nhập đã tạo
   - Cập nhật `PROJECT_ID` bằng ID dự án Firebase

2. Chạy script để đăng ký thiết bị (thường chỉ cần chạy một lần khi thiết bị khởi động lần đầu):

```bash
python3 device_registration.py
```

3. Kiểm tra trong Firebase Console > Cloud Firestore để xác nhận thiết bị đã được đăng ký trong collection `connections`.

### 2. Xử lý streaming video

1. Nạp module v4l2loopback để tạo thiết bị camera ảo:

```bash
sudo modprobe v4l2loopback exclusive_caps=1
```

2. Kiểm tra các thiết bị video đang có:

```bash
v4l2-ctl --list-devices
```

3. Chạy script streaming video:

```bash
# Với thiết lập mặc định (camera vật lý /dev/video0, camera ảo /dev/video1)
python3 video_streaming.py

# Hoặc chỉ định các tham số khác
python3 video_streaming.py --physical-device=/dev/video0 --virtual-device=/dev/video1 --width=640 --height=480 --framerate=30
```

4. Truy cập stream HLS: Mở trình duyệt và truy cập địa chỉ:
```
http://[địa-chỉ-IP-của-Pi]/playlist.m3u8
```

### 3. Thiết lập tự động khởi động khi boot

Tạo dịch vụ systemd để tự động khởi động scripts khi Pi khởi động:

1. Tạo file service cho đăng ký thiết bị:

```bash
sudo nano /etc/systemd/system/device-registration.service
```

Nội dung:
```
[Unit]
Description=Device Registration Service
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /đường/dẫn/đến/device_registration.py
User=pi

[Install]
WantedBy=multi-user.target
```

2. Tạo file service cho video streaming:

```bash
sudo nano /etc/systemd/system/video-streaming.service
```

Nội dung:
```
[Unit]
Description=Video Streaming Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /đường/dẫn/đến/video_streaming.py
User=pi
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. Kích hoạt dịch vụ:

```bash
sudo systemctl enable device-registration.service
sudo systemctl enable video-streaming.service
sudo systemctl start device-registration.service
sudo systemctl start video-streaming.service
```

## Giải Thích Chi Tiết Mã Nguồn

### 1. Script đăng ký thiết bị (`device_registration.py`)

- **Xác thực Firebase:** Script sẽ xác thực với Firebase Authentication bằng email/password để lấy `idToken` cần thiết cho việc ghi dữ liệu vào Cloud Firestore.
- **ID Thiết bị:** Script tạo ID thiết bị duy nhất và lưu vào file cấu hình, đảm bảo rằng ID không thay đổi mỗi khi khởi động lại.
- **Đăng ký vào Cloud Firestore:** Script sẽ gửi thông tin thiết bị tới collection `connections` trong Cloud Firestore, và chỉ đăng ký một lần (kiểm tra trùng lặp trước khi đăng ký).

### 2. Script xử lý streaming video (`video_streaming.py`)

- **Module v4l2loopback:** Script sẽ thiết lập v4l2loopback để tạo thiết bị camera ảo (`/dev/video1`) từ camera vật lý (`/dev/video0`).
- **Sao chép Video:** Sử dụng ffmpeg để sao chép luồng video từ camera vật lý sang thiết bị ảo, cho phép nhiều ứng dụng có thể truy cập đồng thời.
- **Streaming HLS:** Script sử dụng GStreamer để tạo stream HLS từ thiết bị camera ảo, giúp dễ dàng truy cập video từ các thiết bị khác qua mạng.

## Xử Lý Sự Cố

### Vấn đề camera bị chiếm quyền truy cập

Nếu gặp lỗi "device busy" khi truy cập camera:

1. Kiểm tra xem có tiến trình nào đang sử dụng camera:
```bash
fuser -v /dev/video0
```

2. Dừng các tiến trình đó:
```bash
sudo fuser -k /dev/video0
```

### Stream không hoạt động

1. Kiểm tra log của script streaming:
```bash
tail -f /var/log/syslog | grep video_streaming
```

2. Đảm bảo port 80 không bị chặn:
```bash
sudo netstat -tulpn | grep :80
```

3. Kiểm tra quyền truy cập thư mục đầu ra:
```bash
sudo chmod -R 755 /var/www/html
```

## Tham Khảo

- [Firebase REST API Documentation](https://firebase.google.com/docs/reference/rest/database)
- [Cloud Firestore REST API](https://firebase.google.com/docs/firestore/use-rest-api)
- [v4l2loopback Documentation](https://github.com/umlaeute/v4l2loopback)
- [GStreamer Documentation](https://gstreamer.freedesktop.org/documentation/)
- [HTTP Live Streaming (HLS) Specification](https://developer.apple.com/streaming/)