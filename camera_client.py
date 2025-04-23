# File: camera_client.py
# Module xử lý chụp ảnh và gửi hình ảnh đến server

import os
import time
import datetime
import threading
import subprocess
import re
import base64
import json
import websocket
import requests
from io import BytesIO
from config import (
    PHOTO_DIR, TEMP_DIR, DEVICE_ID, IMAGE_API_ENDPOINT, 
    IMAGE_WS_ENDPOINT, PHOTO_INTERVAL, RECONNECT_INTERVAL
)
from utils import get_timestamp, make_api_request, logger

# Flag cho việc sử dụng PiCamera hoặc USB camera
PICAMERA_AVAILABLE = False

try:
    from PIL import Image
    logger.info("Đã phát hiện thư viện PIL")
except ImportError:
    logger.warning("CẢNH BÁO: Không tìm thấy thư viện PIL. Chức năng xử lý ảnh sẽ bị hạn chế.")

try:
    from picamera import PiCamera
    PICAMERA_AVAILABLE = True
    logger.info("Đã phát hiện PiCamera.")
except ImportError:
    logger.warning("Không tìm thấy PiCamera. Sẽ sử dụng USB camera nếu có.")


class CameraClient:
    """
    Client xử lý chụp ảnh và gửi hình ảnh đến server
    """
    def __init__(self, use_websocket=True, interval=PHOTO_INTERVAL):
        """
        Khởi tạo camera client
        
        Args:
            use_websocket (bool): Sử dụng WebSocket cho kết nối thời gian thực
            interval (int): Khoảng thời gian giữa các lần chụp ảnh (giây)
        """
        self.use_websocket = use_websocket
        self.interval = interval
        self.running = False
        self.ws = None
        self.ws_connected = False
        self.ws_thread = None
        self.photo_thread = None
        
        # Tạo các thư mục cần thiết
        os.makedirs(PHOTO_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        
    def start(self):
        """
        Khởi động camera client
        """
        self.running = True
        
        # Khởi động kết nối WebSocket nếu cần
        if self.use_websocket:
            self.ws_thread = threading.Thread(target=self._websocket_thread)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
        # Khởi động thread chụp ảnh định kỳ
        self.photo_thread = threading.Thread(target=self._photo_thread)
        self.photo_thread.daemon = True
        self.photo_thread.start()
            
        logger.info("Camera client đã khởi động")
        return True
        
    def stop(self):
        """
        Dừng camera client
        """
        self.running = False
        
        # Đóng kết nối WebSocket nếu có
        if self.ws and self.ws_connected:
            self.ws.close()
            self.ws_connected = False
            
        # Đợi thread xử lý kết thúc
        if self.photo_thread and self.photo_thread.is_alive():
            self.photo_thread.join(timeout=1.0)  # Đợi tối đa 1 giây
            
        logger.info("Camera client đã dừng")
        
    def _websocket_thread(self):
        """
        Thread xử lý kết nối WebSocket
        """
        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'request':
                    # Server yêu cầu hình ảnh mới
                    logger.info("Nhận yêu cầu chụp ảnh từ server")
                    
                    # Chụp ảnh mới và gửi qua WebSocket
                    threading.Thread(target=self.capture_and_send_photo).start()
                    
                elif msg_type == 'error':
                    # Thông báo lỗi
                    msg = data.get('message', '')
                    details = data.get('details', '')
                    logger.error(f"Lỗi từ server hình ảnh: {msg}")
                    if details:
                        logger.error(f"Chi tiết: {details}")
            
            except json.JSONDecodeError:
                logger.error(f"Không thể giải mã thông điệp WebSocket: {message}")
            except Exception as e:
                logger.error(f"Lỗi khi xử lý thông điệp WebSocket: {e}")

        def on_error(ws, error):
            logger.error(f"Lỗi WebSocket hình ảnh: {error}")
            self.ws_connected = False

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"WebSocket hình ảnh đã đóng: {close_status_code} - {close_msg}")
            self.ws_connected = False
            
            # Thử kết nối lại sau một khoảng thời gian nếu client vẫn đang chạy
            if self.running:
                logger.info(f"Đang thử kết nối lại WebSocket hình ảnh sau {RECONNECT_INTERVAL} giây...")
                time.sleep(RECONNECT_INTERVAL)
                self._connect_websocket()

        def on_open(ws):
            logger.info("Đã kết nối WebSocket tới server xử lý hình ảnh")
            self.ws_connected = True
            
            # Gửi thông tin thiết bị
            self.ws.send(json.dumps({
                'type': 'connect',
                'client_id': DEVICE_ID,
                'timestamp': time.time()
            }))
        
        # Khởi tạo và kết nối WebSocket
        def _connect_websocket():
            try:
                if hasattr(self, 'ws') and self.ws:
                    self.ws.close()
                    
                logger.info(f"Đang kết nối tới {IMAGE_WS_ENDPOINT}/{DEVICE_ID}")
                self.ws = websocket.WebSocketApp(
                    f"{IMAGE_WS_ENDPOINT}/{DEVICE_ID}",
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Lỗi kết nối WebSocket hình ảnh: {e}")
                self.ws_connected = False
                time.sleep(RECONNECT_INTERVAL)  # Đợi trước khi thử lại
        
        self._connect_websocket = _connect_websocket
        
        # Vòng lặp kết nối lại nếu mất kết nối
        while self.running:
            if not self.ws_connected:
                _connect_websocket()
            time.sleep(1)
    
    def _photo_thread(self):
        """
        Thread chụp ảnh theo khoảng thời gian định kỳ và gửi đến server
        """
        while self.running:
            try:
                # Chụp ảnh và gửi đến server
                self.capture_and_send_photo()
                
                # Đợi đến lần chụp tiếp theo
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Lỗi trong thread chụp ảnh: {e}")
                time.sleep(self.interval)
    
    def detect_video_devices(self):
        """Phát hiện và trả về thông tin các thiết bị camera USB"""
        try:
            # Sử dụng lệnh v4l2-ctl để liệt kê các thiết bị video
            proc = subprocess.run(['v4l2-ctl', '--list-devices'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            devices_output = proc.stdout.decode()
            
            if not devices_output.strip():
                # Thử dùng cách khác để liệt kê thiết bị video
                proc = subprocess.run(['ls', '-la', '/dev/video*'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                devices_output = proc.stdout.decode()
                
                if 'No such file or directory' in devices_output:
                    return []
                    
                # Phân tích đầu ra để tìm thiết bị video
                video_devices = []
                for line in devices_output.splitlines():
                    match = re.search(r'/dev/video(\d+)', line)
                    if match:
                        video_devices.append({
                            'device': match.group(0),
                            'index': match.group(1),
                            'name': f"Video Device {match.group(1)}"
                        })
                return video_devices
            
            # Phân tích đầu ra của v4l2-ctl
            devices = []
            current_device = None
            for line in devices_output.splitlines():
                if ':' in line and '/dev/video' not in line:
                    # Đây là tên thiết bị
                    current_device = line.strip().rstrip(':')
                elif '/dev/video' in line:
                    # Đây là đường dẫn thiết bị
                    match = re.search(r'/dev/video(\d+)', line)
                    if match and current_device:
                        devices.append({
                            'device': match.group(0),
                            'index': match.group(1),
                            'name': current_device
                        })
            return devices
        except Exception as e:
            logger.error(f"Lỗi khi phát hiện thiết bị camera: {e}")
            return []
    
    def get_best_video_device(self):
        """Chọn thiết bị camera phù hợp nhất"""
        devices = self.detect_video_devices()
        
        if not devices:
            return None
            
        # Ưu tiên USB camera thường có từ camera, webcam, usb trong tên
        for device in devices:
            if 'camera' in device.get('name', '').lower() or 'webcam' in device.get('name', '').lower() or 'usb' in device.get('name', '').lower():
                return device
        
        # Nếu không tìm thấy, chọn thiết bị đầu tiên
        if len(devices) > 0:
            return devices[0]
            
        return None
    
    def capture_with_fswebcam(self, output_path):
        """Chụp ảnh bằng fswebcam (cho USB camera)"""
        try:
            # Tìm thiết bị camera
            device = self.get_best_video_device()
            if not device:
                logger.warning("Không tìm thấy thiết bị camera USB")
                return None
                    
            # Dùng fswebcam để chụp ảnh
            device_path = device['device']
            logger.info(f"Bắt đầu chụp ảnh từ thiết bị {device_path}...")
            
            # Đảm bảo thư mục tạm tồn tại
            os.makedirs(TEMP_DIR, exist_ok=True)
            
            # Đường dẫn đến file tạm
            temp_path = os.path.join(TEMP_DIR, "temp_capture.jpg")
            
            # Chụp ảnh với fswebcam
            subprocess.run([
                'fswebcam',
                '-q',                   # Chế độ im lặng (không hiển thị banner)
                '-r', '1280x720',       # Độ phân giải
                '--no-banner',          # Không hiển thị banner
                '-d', device_path,      # Thiết bị camera
                '--jpeg', '85',         # Chất lượng JPEG
                '-F', '5',              # Số frames để bỏ qua (giúp camera ổn định)
                temp_path               # Đường dẫn file đầu ra
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            
            # Kiểm tra file có được tạo thành công
            if not os.path.exists(temp_path):
                logger.error("Lỗi chụp ảnh - file không được tạo")
                return None
                
            if os.path.getsize(temp_path) < 1000:  # Kiểm tra kích thước tối thiểu
                logger.error("Lỗi chụp ảnh - file quá nhỏ, có thể bị lỗi")
                os.remove(temp_path)
                return None
                
            # Di chuyển file từ thư mục tạm đến thư mục đích
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            os.rename(temp_path, output_path)
            
            logger.info(f"Đã chụp ảnh: {output_path}")
            return output_path
                    
        except Exception as e:
            logger.error(f"Lỗi khi chụp ảnh với fswebcam: {e}")
            # Dọn dẹp file tạm nếu có lỗi
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
            return None
    
    def capture_with_libcamera(self, output_path):
        """Chụp ảnh bằng libcamera-still (cho Pi Camera)"""
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Sử dụng libcamera-still để chụp ảnh (hỗ trợ Raspberry Pi mới)
            subprocess.run([
                'libcamera-still',
                '-t', '1000',           # Thời gian chờ 1 giây
                '-n',                   # Không hiển thị preview
                '--width', '1280',      # Chiều rộng
                '--height', '720',      # Chiều cao
                '-o', output_path       # Đường dẫn file đầu ra
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            
            # Kiểm tra file có được tạo thành công
            if not os.path.exists(output_path):
                logger.error("Lỗi chụp ảnh với libcamera - file không được tạo")
                return None
                
            if os.path.getsize(output_path) < 1000:  # Kiểm tra kích thước tối thiểu
                logger.error("Lỗi chụp ảnh với libcamera - file quá nhỏ, có thể bị lỗi")
                os.remove(output_path)
                return None
                
            logger.info(f"Đã chụp ảnh với libcamera: {output_path}")
            return output_path
                    
        except Exception as e:
            logger.error(f"Lỗi khi chụp ảnh với libcamera: {e}")
            return None
    
    def capture_with_picamera(self, output_path):
        """Chụp ảnh bằng module PiCamera"""
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            camera = PiCamera()
            camera.resolution = (1280, 720)
            
            # Khởi động camera và chờ cân bằng độ sáng
            camera.start_preview()
            time.sleep(2)  # Chờ camera điều chỉnh độ sáng
            
            # Chụp ảnh
            camera.capture(output_path)
            camera.stop_preview()
            camera.close()
            
            logger.info(f"Đã chụp ảnh với PiCamera: {output_path}")
            return output_path
        
        except Exception as e:
            logger.error(f"Lỗi khi chụp ảnh với PiCamera: {e}")
            return None
    
    def capture_photo(self):
        """
        Chụp ảnh từ camera và lưu vào thư mục chỉ định
        
        Returns:
            str: Đường dẫn đến file ảnh đã chụp, hoặc None nếu thất bại
        """
        # Tạo thư mục nếu chưa tồn tại
        os.makedirs(PHOTO_DIR, exist_ok=True)
        
        # Tạo tên file với timestamp
        string_timestamp, _ = get_timestamp()
        filename = f"photo_{string_timestamp}.jpg"
        filepath = os.path.join(PHOTO_DIR, filename)
        
        # Thử chụp ảnh bằng các phương pháp khác nhau
        
        # Thử với USB camera trước (fswebcam)
        result = self.capture_with_fswebcam(filepath)
        if result:
            return result
            
        # Nếu không có USB camera, thử dùng PiCamera
        if PICAMERA_AVAILABLE:
            result = self.capture_with_picamera(filepath)
            if result:
                return result
        
        # Thử dùng libcamera-still (cho Raspberry Pi OS mới)
        result = self.capture_with_libcamera(filepath)
        if result:
            return result
            
        logger.error("Không thể chụp ảnh: Không tìm thấy thiết bị camera hỗ trợ")
        return None
    
    def get_image_as_base64(self, image_path, quality="high"):
        """
        Chuyển đổi hình ảnh thành chuỗi base64 với chất lượng tùy chỉnh
        
        Args:
            image_path (str): Đường dẫn đến file hình ảnh
            quality (str): Chất lượng hình ảnh ("high", "medium", "low")
            
        Returns:
            str: Chuỗi base64 của dữ liệu hình ảnh
        """
        try:
            from PIL import Image
            import io
            
            # Mở ảnh và nén theo chất lượng
            with Image.open(image_path) as img:
                # Điều chỉnh chất lượng và kích thước theo yêu cầu
                if quality == "medium":
                    # Giảm kích thước xuống 50% và nén với chất lượng 70%
                    new_size = (img.width // 2, img.height // 2)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    compress_quality = 70
                elif quality == "low":
                    # Giảm kích thước xuống 30% và nén với chất lượng 50%
                    new_size = (img.width // 3, img.height // 3)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    compress_quality = 50
                else:
                    # Chất lượng cao - giữ nguyên kích thước, nén nhẹ
                    compress_quality = 85
                
                # Lưu ảnh vào buffer với định dạng JPEG và nén
                buffer = io.BytesIO()
                img.convert('RGB').save(buffer, format="JPEG", quality=compress_quality)
                image_data = buffer.getvalue()
                
                # Mã hóa thành base64
                base64_image = base64.b64encode(image_data).decode('utf-8')
                return base64_image
                
        except Exception as e:
            logger.error(f"Lỗi khi chuyển đổi hình ảnh sang base64: {e}")
            
            # Nếu không có PIL, đọc file trực tiếp
            try:
                with open(image_path, "rb") as image_file:
                    return base64.b64encode(image_file.read()).decode('utf-8')
            except Exception as e2:
                logger.error(f"Lỗi khi đọc file hình ảnh: {e2}")
                return None
    
    def send_image_via_websocket(self, image_path, timestamp, quality="high"):
        """
        Gửi hình ảnh qua WebSocket theo định dạng yêu cầu của server
        
        Args:
            image_path (str): Đường dẫn đến file hình ảnh
            timestamp (float): Thời gian chụp ảnh
            quality (str): Chất lượng hình ảnh ("high", "medium", "low")
            
        Returns:
            bool: True nếu gửi thành công, False nếu không
        """
        if not self.ws_connected:
            logger.warning("Không có kết nối WebSocket, không thể gửi hình ảnh")
            return False
        
        try:
            # Chuyển đổi hình ảnh thành base64
            image_base64 = self.get_image_as_base64(image_path, quality)
            if not image_base64:
                return False
                
            # Tạo message theo định dạng yêu cầu của server
            message = {
                'type': 'image',
                'timestamp': timestamp,
                'device_id': DEVICE_ID,
                'quality': quality,
                'image_data': image_base64
            }
            
            # Gửi qua WebSocket
            self.ws.send(json.dumps(message))
            logger.info(f"Đã gửi hình ảnh qua WebSocket lúc {timestamp} (chất lượng: {quality})")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi gửi hình ảnh qua WebSocket: {e}")
            return False
    
    def send_image_to_server(self, image_path, timestamp, quality="high"):
        """
        Gửi hình ảnh đến server qua REST API
        
        Args:
            image_path (str): Đường dẫn đến file hình ảnh
            timestamp (float): Thời gian chụp ảnh
            quality (str): Chất lượng hình ảnh ("high", "medium", "low")
            
        Returns:
            bool: True nếu gửi thành công, False nếu không
        """
        if not os.path.exists(image_path):
            logger.error(f"Không tìm thấy file hình ảnh: {image_path}")
            return False
            
        try:
            # Gửi file qua REST API
            with open(image_path, 'rb') as image_file:
                files = {
                    'image': (os.path.basename(image_path), image_file, 'image/jpeg')
                }
                
                data = {
                    'timestamp': timestamp,
                    'device_id': DEVICE_ID,
                    'quality': quality
                }
                
                logger.info(f"Đang gửi hình ảnh đến server: {os.path.basename(image_path)}")
                success, response = make_api_request(
                    url=IMAGE_API_ENDPOINT,
                    method='POST',
                    data=data,
                    files=files
                )
                
                if success:
                    logger.info(f"Đã gửi hình ảnh thành công")
                    return True
                else:
                    logger.error(f"Lỗi khi gửi hình ảnh: {response}")
                    return False
                    
        except Exception as e:
            logger.error(f"Lỗi khi gửi hình ảnh đến server: {e}")
            return False
    
    def capture_and_send_photo(self, quality="high"):
        """
        Chụp ảnh và gửi đến server
        
        Args:
            quality (str): Chất lượng hình ảnh ("high", "medium", "low")
            
        Returns:
            bool: True nếu thành công, False nếu không
        """
        # Chụp ảnh
        image_path = self.capture_photo()
        
        if not image_path:
            logger.error("Không thể chụp ảnh để gửi đến server")
            return False
            
        # Gửi hình ảnh đến server
        _, timestamp = get_timestamp()
        if self.use_websocket and self.ws_connected:
            # Ưu tiên gửi qua WebSocket nếu có kết nối
            return self.send_image_via_websocket(image_path, timestamp, quality)
        else:
            # Nếu không có kết nối WebSocket, gửi qua REST API
            return self.send_image_to_server(image_path, timestamp, quality)


# Test module khi chạy trực tiếp
if __name__ == "__main__":
    # Khởi tạo client
    camera_client = CameraClient(use_websocket=True, interval=10)  # Chụp ảnh mỗi 10 giây
    
    # Bắt đầu client
    camera_client.start()
    
    try:
        # Cho WebSocket client chạy một lát
        logger.info("Giữ kết nối và chụp ảnh trong 60 giây...")
        time.sleep(60)
        
    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu dừng")
    finally:
        # Dừng client
        camera_client.stop()
        logger.info("Đã kết thúc thử nghiệm")