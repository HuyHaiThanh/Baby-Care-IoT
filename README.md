# Baby-Care-IoT

Hệ thống giám sát trẻ em sử dụng Raspberry Pi cho phép truyền dữ liệu âm thanh từ xa.

## Hướng dẫn kết nối để lấy âm thanh từ Raspberry Pi

### 1. Sử dụng client có sẵn

Cách đơn giản nhất để kết nối và lấy âm thanh từ Raspberry Pi là sử dụng client được cung cấp:

```bash
# Cài đặt các thư viện cần thiết
pip install -r requirements.txt

# Chạy client với địa chỉ IP của Raspberry Pi
python main.py --server 192.168.1.xxx
```

### 2. Sử dụng HTTP API để lấy âm thanh

Nếu bạn muốn tích hợp vào ứng dụng của mình, bạn có thể sử dụng HTTP API:

```
# Lấy âm thanh mới nhất
GET http://192.168.1.xxx:8000/api/audio

# Yêu cầu ghi âm mới (với thời lượng 5 giây)
GET http://192.168.1.xxx:8000/api/record?duration=5
```

Kết quả trả về dưới dạng JSON với dữ liệu âm thanh được mã hóa Base64:

```json
{
  "status": "success",
  "data": {
    "audio": {
      "data": "BASE64_ENCODED_AUDIO_DATA",
      "timestamp": "2025-04-22T10:30:45.123456",
      "device_name": "Baby Monitor Pi",
      "file_name": "audio_20250422_103045.wav",
      "is_crying": false
    }
  }
}
```

### 3. Sử dụng WebSocket để nhận âm thanh theo thời gian thực

Để nhận thông báo và dữ liệu âm thanh theo thời gian thực, đặc biệt là khi phát hiện tiếng khóc:

```javascript
// Kết nối WebSocket
const socket = new WebSocket('ws://192.168.1.xxx:8765');

// Gửi yêu cầu lấy âm thanh
socket.send(JSON.stringify({
  "action": "request_audio"
}));

// Nhận dữ liệu
socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'audio') {
    const audioData = data.data; // Dữ liệu âm thanh Base64
    const isCrying = data.is_crying || false;
    
    // Xử lý âm thanh ở đây
    if (isCrying) {
      console.log("Phát hiện tiếng khóc của em bé!");
      // Thông báo hoặc phát âm thanh
    }
  }
};
```

### 4. Tích hợp vào code Python của bạn

Bạn có thể sử dụng lớp `AudioClient` để tích hợp vào ứng dụng Python của mình:

```python
from audio_client import AudioClient
import time

# Callback khi nhận được âm thanh mới
def on_new_audio(audio_path, is_crying):
    print(f"Đã nhận âm thanh mới: {audio_path}")
    if is_crying:
        print("⚠️ CẢNH BÁO: Phát hiện tiếng khóc của em bé!")
    
# Callback khi trạng thái kết nối thay đổi
def on_connection_change(connected):
    print(f"Trạng thái kết nối: {'Đã kết nối' if connected else 'Mất kết nối'}")

# Khởi tạo và cấu hình client
client = AudioClient()
client.set_callback_new_audio(on_new_audio)
client.set_callback_connection_change(on_connection_change)

# Bắt đầu client
client.start()

try:
    while True:
        # Chương trình chính của bạn
        time.sleep(1)
except KeyboardInterrupt:
    print("Dừng chương trình...")
finally:
    # Dừng client khi kết thúc
    client.stop()
```

### 5. Các tính năng của AudioClient

- **Tự động phát hiện và thông báo tiếng khóc**: AudioClient có thể tự động phân tích và thông báo khi phát hiện tiếng khóc của em bé
- **Tự động kết nối lại**: Client sẽ tự động kết nối lại khi mất kết nối
- **Phát âm thanh**: Có thể phát âm thanh đã nhận từ server

### Lưu ý

- Thay `192.168.1.xxx` bằng địa chỉ IP thực của Raspberry Pi trong mạng của bạn
- Đảm bảo Raspberry Pi và thiết bị của bạn kết nối cùng một mạng
- Kiểm tra tường lửa nếu không thể kết nối
- Đảm bảo cài đặt thư viện `pyaudio` để phát âm thanh: `pip install pyaudio`
- Nếu gặp vấn đề khi cài đặt pyaudio trên Windows, bạn có thể cần phải cài đặt các thư viện bổ sung hoặc sử dụng file wheel
- Khi phát hiện tiếng khóc, hệ thống sẽ tự động thông báo qua callback đã đăng ký

