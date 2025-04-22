# Baby-Care-IoT

Hệ thống giám sát trẻ em (Baby Monitor) sử dụng Raspberry Pi với khả năng truyền dữ liệu hình ảnh qua API và WebSocket.

## Mục lục
1. [Tổng quan](#tổng-quan)
2. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
3. [Cách cài đặt](#cách-cài-đặt)
4. [Kết nối đến Raspberry Pi](#kết-nối-đến-raspberry-pi)
   - [Kết nối thông qua HTTP API](#kết-nối-thông-qua-http-api)
   - [Kết nối thông qua WebSocket](#kết-nối-thông-qua-websocket)

## Tổng quan

Baby-Care-IoT là một hệ thống giám sát trẻ em sử dụng Raspberry Pi, cho phép:
- Truyền hình ảnh camera theo thời gian thực
- Truy cập dữ liệu từ xa thông qua API hoặc WebSocket

## Yêu cầu hệ thống

- Python 3.6 trở lên
- Các thư viện được liệt kê trong file `requirements.txt`

## Cách cài đặt

1. Clone repository này về máy tính của bạn
2. Cài đặt các thư viện cần thiết:
   ```
   pip install -r requirements.txt
   ```
3. Chạy client photo:
   ```
   python main.py --server [địa_chỉ_IP_của_Raspberry_Pi]
   ```

## Kết nối đến Raspberry Pi

Hệ thống Baby-Care-IoT cung cấp hai cách để kết nối và lấy hình ảnh từ Raspberry Pi:

### Kết nối thông qua HTTP API

Hệ thống cung cấp các API endpoint để lấy hình ảnh.

#### Thông tin cơ bản
- **Base URL**: `http://[địa_chỉ_IP_của_Raspberry_Pi]:8000/api`
- **Phương thức hỗ trợ**: GET
- **Format dữ liệu trả về**: JSON

#### Các API endpoint có sẵn

1. **Kiểm tra trạng thái hệ thống**
   ```
   GET /api/status
   ```

2. **Lấy dữ liệu hình ảnh mới nhất**
   ```
   GET /api/latest
   ```

3. **Lấy hình ảnh mới nhất**
   ```
   GET /api/photo
   ```

4. **Yêu cầu chụp ảnh mới**
   ```
   GET /api/capture
   ```

### Kết nối thông qua WebSocket

Hệ thống cũng hỗ trợ kết nối WebSocket để truyền dữ liệu hình ảnh theo thời gian thực.

#### Thông tin cơ bản
- **WebSocket URL**: `ws://[địa_chỉ_IP_của_Raspberry_Pi]:8765`
- **Format dữ liệu**: JSON

#### Cách sử dụng photo_client.py

File `photo_client.py` trong dự án này cung cấp một client mẫu để kết nối với Raspberry Pi qua WebSocket và nhận hình ảnh. 

1. **Chạy client photo với giao diện đồ họa**:
   ```
   python main.py --server [địa_chỉ_IP_của_Raspberry_Pi]
   ```

2. **Sử dụng client trong code của bạn**:
   ```python
   from photo_client import PhotoClient
   import asyncio

   async def main():
       # Tạo callback khi nhận được ảnh mới
       def on_image_received(image_path, image):
           print(f"Đã nhận ảnh mới: {image_path}")
           # Xử lý ảnh ở đây
       
       # Khởi tạo client với callback
       client = PhotoClient(on_image_received=on_image_received)
       
       # Kết nối đến server
       connected = await client.connect()
       
       if connected:
           # Gửi yêu cầu lấy ảnh mới nhất (chất lượng: high, medium, low)
           await client.request_latest_image(quality="high")
           
           # Lắng nghe tin nhắn từ server
           await client.listen()

   # Chạy client
   asyncio.run(main())
   ```

#### Giao thức WebSocket

1. **Gửi yêu cầu lấy hình ảnh**:
   ```json
   {
     "action": "request_image",
     "quality": "high",
     "paths": [
       "/home/pi/Baby-Care-IoT/camera_data/photos",
       "camera_data/photos"
     ]
   }
   ```
   
   Các tùy chọn chất lượng:
   - `high` - Chất lượng cao, kích thước lớn
   - `medium` - Chất lượng trung bình, kích thước giảm 50%
   - `low` - Chất lượng thấp, kích thước nhỏ

2. **Nhận dữ liệu hình ảnh**:
   ```json
   {
     "type": "image",
     "data": "BASE64_ENCODED_IMAGE_DATA",
     "timestamp": "2025-04-22T10:30:45.123456",
     "device_name": "Baby Monitor Pi",
     "file_name": "photo_20250422_103045.jpg",
     "quality": "high"
   }
   ```

#### Xử lý kết nối tự động

Client `photo_client.py` đã được thiết kế để tự động kết nối lại khi mất kết nối, tự động điều chỉnh chất lượng hình ảnh dựa trên tình trạng kết nối, và có thể xử lý các lỗi phổ biến. Bạn có thể sử dụng nó như một tham khảo khi xây dựng client riêng của mình.
