# Baby-Care-IoT

Hệ thống giám sát trẻ em (Baby Monitor) sử dụng Raspberry Pi với khả năng truyền dữ liệu hình ảnh và âm thanh qua API và WebSocket.

## Mục lục
1. [Tổng quan](#tổng-quan)
2. [Cấu trúc hệ thống](#cấu-trúc-hệ-thống)
3. [Kết nối thông qua HTTP API](#kết-nối-thông-qua-http-api)
4. [Kết nối thông qua WebSocket](#kết-nối-thông-qua-websocket)

## Tổng quan

Baby-Care-IoT là một hệ thống giám sát trẻ em sử dụng Raspberry Pi, cho phép:
- Truyền hình ảnh camera theo thời gian thực
- Ghi âm và phát hiện tiếng khóc của trẻ
- Truy cập dữ liệu từ xa thông qua API hoặc WebSocket

## Cấu trúc hệ thống

- **HTTP Server (Port 8000)**: Cung cấp RESTful API để truy cập dữ liệu
- **WebSocket Server (Port 8765)**: Cho phép kết nối hai chiều theo thời gian thực
- **Camera Handler**: Quản lý việc chụp ảnh
- **Audio Handler**: Quản lý việc ghi âm và phân tích âm thanh

## Kết nối thông qua HTTP API

### Thông tin cơ bản
- **Base URL**: `http://[địa_chỉ_IP]:8000/api`
- **Phương thức hỗ trợ**: GET
- **Format dữ liệu trả về**: JSON

### Các endpoint có sẵn

#### 1. Kiểm tra trạng thái hệ thống
```
GET /api/status
```
Kết quả trả về:
```json
{
    "status": "online",
    "device_name": "Baby Monitor Pi",
    "crying_detected": false,
    "last_update": "2025-04-22T10:30:45.123456",
    "has_photo": true,
    "has_audio": true
}
```

#### 2. Lấy dữ liệu mới nhất (cả hình ảnh và âm thanh)
```
GET /api/latest
```
Kết quả trả về bao gồm dữ liệu hình ảnh và âm thanh được mã hóa Base64.

#### 3. Lấy hình ảnh mới nhất
```
GET /api/photo
```
Kết quả trả về:
```json
{
    "status": "success",
    "data": {
        "photo": {
            "data": "BASE64_ENCODED_IMAGE_DATA",
            "timestamp": "2025-04-22T10:30:45.123456",
            "device_name": "Baby Monitor Pi",
            "file_name": "photo_20250422_103045.jpg"
        },
        "last_update": "2025-04-22T10:30:45.123456",
        "device_name": "Baby Monitor Pi"
    }
}
```

#### 4. Lấy âm thanh mới nhất
```
GET /api/audio
```

#### 5. Yêu cầu chụp ảnh mới
```
GET /api/capture
```

#### 6. Yêu cầu ghi âm mới
```
GET /api/record?duration=5
```
Tham số `duration` xác định thời gian ghi âm (giây), mặc định là 5 giây.

## Kết nối thông qua WebSocket

### Thông tin cơ bản
- **WebSocket URL**: `ws://[địa_chỉ_IP]:8765`
- **Format dữ liệu**: JSON

### Kết nối và nhận dữ liệu

#### Định dạng tin nhắn gửi đến server

```json
{
  "action": "request_image",
  "quality": "high"
}
```

Các action hỗ trợ:
- `request_image`: Yêu cầu hình ảnh mới nhất
- `request_audio`: Yêu cầu âm thanh mới nhất
- `request_all`: Yêu cầu cả hình ảnh và âm thanh

Tham số chất lượng (`quality`):
- `high` - Chất lượng cao, kích thước lớn
- `medium` - Chất lượng trung bình, kích thước giảm 50%
- `low` - Chất lượng thấp, kích thước nhỏ

#### Định dạng dữ liệu hình ảnh từ server

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

#### Định dạng dữ liệu âm thanh từ server

```json
{
  "type": "audio",
  "data": "BASE64_ENCODED_AUDIO_DATA",
  "timestamp": "2025-04-22T10:30:45.123456", 
  "device_name": "Baby Monitor Pi",
  "file_name": "audio_20250422_103045.mp3"
}
