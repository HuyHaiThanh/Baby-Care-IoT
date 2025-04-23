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
        
        # Bộ đếm gửi dữ liệu
        self.sent_success_count = 0
        self.sent_fail_count = 0
        self.total_photos_taken = 0
        
        # Theo dõi file đang xử lý
        self.current_photo_file = "Không có"
        self.processing_status = "Đang chờ"
        self.next_photo_time = time.time() + interval
        
        # Thêm bộ đếm thời gian
        self.last_capture_time = time.time()
        self.last_sent_time = 0
        self.capture_duration = 0  # Thời gian chụp ảnh (giây)
        self.sending_duration = 0  # Thời gian gửi ảnh (giây)
        
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
                    
                # Thêm token xác thực vào URL WebSocket
                auth_token = f"?token={DEVICE_ID}"
                websocket_url = f"{IMAGE_WS_ENDPOINT}/{DEVICE_ID}{auth_token}"
                logger.info(f"Đang kết nối tới {websocket_url}")
                
                # Thêm header xác thực
                headers = {
                    "Authorization": f"Bearer {DEVICE_ID}",
                    "X-Device-ID": DEVICE_ID
                }
                
                self.ws = websocket.WebSocketApp(
                    websocket_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                    header=headers
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
    
    def capture_with_ffmpeg(self, output_path):
        """Chụp ảnh bằng ffmpeg (nhanh và hiệu quả)"""
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Tìm thiết bị camera
            device_path = '/dev/video0'  # Mặc định trên Linux
            
            # Với Windows, sử dụng DirectShow
            if os.name == 'nt':
                # Thử với thiết bị DirectShow và không chỉ định định dạng đầu vào
                command = [
                    'ffmpeg',
                    '-y',                       # Ghi đè file nếu có
                    '-f', 'dshow',              # Format DirectShow cho Windows
                    '-video_size', '320x240',   # Độ phân giải thấp
                    '-i', 'video=Webcam',       # Tên thiết bị webcam thông thường
                    '-vframes', '1',            # Chỉ lấy 1 frame
                    '-q:v', '15',               # Chất lượng thấp
                    '-loglevel', 'error',       # Chỉ hiển thị lỗi
                    output_path
                ]
            else:
                # Cho Linux, thử không chỉ định định dạng đầu vào để tránh lỗi
                command = [
                    'ffmpeg',
                    '-y',                       # Ghi đè file nếu có
                    '-f', 'v4l2',               # Format v4l2 cho Linux
                    '-video_size', '160x120',   # Độ phân giải cực thấp để tăng tốc
                    '-i', device_path,          # Thiết bị camera
                    '-vframes', '1',            # Chỉ lấy 1 frame
                    '-q:v', '15',               # Chất lượng thấp để tăng tốc
                    '-loglevel', 'error',       # Chỉ hiển thị lỗi
                    output_path
                ]
            
            # Tăng timeout lên 5 giây để cho webcam thời gian khởi động
            logger.info(f"Đang chụp ảnh với ffmpeg từ {device_path if os.name != 'nt' else 'webcam'}")
            result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
            
            # Kiểm tra file đã được tạo thành công
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
                
            # Nếu thất bại với cấu hình đầu tiên, thử cấu hình thứ hai (trên Linux)
            if os.name != 'nt':
                logger.info("Thử lại với cấu hình khác...")
                # Thử với yuv422p và không chỉ định định dạng đầu vào
                command_alt = [
                    'ffmpeg',
                    '-y',
                    '-f', 'v4l2',
                    '-s', '160x120',           # Sử dụng -s thay vì -video_size
                    '-i', device_path,
                    '-vframes', '1',
                    '-q:v', '20',              # Chất lượng thấp hơn
                    '-loglevel', 'error',
                    output_path
                ]
                
                result = subprocess.run(command_alt, stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                
                # Kiểm tra file đã được tạo thành công
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    return output_path
            
            # Nếu vẫn thất bại, trả về lỗi
            stderr = result.stderr.decode()
            logger.error(f"Lỗi ffmpeg: {stderr}")
            return None
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Quá thời gian chụp ảnh với ffmpeg - thử phương pháp khác")
            # Thử chụp với fswebcam trong trường hợp ffmpeg bị timeout
            if os.name != 'nt':
                try:
                    logger.info("Thử chụp với fswebcam thay thế...")
                    subprocess.run([
                        'fswebcam',
                        '-q',                   # Chế độ im lặng
                        '-r', '160x120',        # Độ phân giải thấp
                        '--no-banner',          # Không hiển thị banner
                        '-d', device_path,      # Thiết bị camera
                        '--jpeg', '50',         # Chất lượng JPEG thấp
                        '-F', '1',              # Số frames để bỏ qua (giảm xuống 1)
                        output_path             # Đường dẫn file đầu ra
                    ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
                    
                    # Kiểm tra file có được tạo thành công
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        logger.info("Đã chụp thành công với fswebcam")
                        return output_path
                except Exception as e:
                    logger.error(f"Fswebcam thất bại: {e}")
            return None
        except Exception as e:
            logger.error(f"Lỗi khi chụp ảnh với ffmpeg: {e}")
            return None
    
    def capture_with_opencv(self, output_path):
        """Chụp ảnh bằng OpenCV (nhanh và đơn giản)"""
        try:
            import cv2
            # Mở camera
            cap = cv2.VideoCapture(0)  # Sử dụng camera đầu tiên
            
            if not cap.isOpened():
                logger.error("Không thể mở camera với OpenCV")
                return None
            
            # Đặt độ phân giải thấp để tăng tốc
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
            
            # Đọc frame
            ret, frame = cap.read()
            cap.release()  # Giải phóng camera ngay lập tức
            
            if not ret:
                logger.error("Không thể đọc frame từ camera")
                return None
                
            # Lưu frame
            cv2.imwrite(output_path, frame)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Đã chụp ảnh với OpenCV: {output_path}")
                return output_path
            return None
        except ImportError:
            logger.warning("Không tìm thấy thư viện OpenCV")
            return None
        except Exception as e:
            logger.error(f"Lỗi khi chụp ảnh với OpenCV: {e}")
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
        
        # Đầu tiên thử dùng OpenCV vì nó thường nhanh và đáng tin cậy hơn
        logger.info("Đang thử chụp ảnh bằng OpenCV...")
        result = self.capture_with_opencv(filepath)
        if result:
            return result
        
        # Nếu OpenCV thất bại, thử với ffmpeg
        logger.info("OpenCV thất bại hoặc không có sẵn, đang thử với ffmpeg...")
        result = self.capture_with_ffmpeg(filepath)
        if result:
            return result
            
        logger.error("Không thể chụp ảnh: Cả OpenCV và ffmpeg đều thất bại")
        return None
    
    def get_image_as_base64(self, image_path, quality="high"):
        """
        Chuyển đổi hình ảnh thành chuỗi base64 không thay đổi kích thước
        
        Args:
            image_path (str): Đường dẫn đến file hình ảnh
            quality (str): Tham số không sử dụng (giữ cho tương thích)
            
        Returns:
            str: Chuỗi base64 của dữ liệu hình ảnh
        """
        try:
            # Đọc file ảnh trực tiếp và mã hóa base64
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Lỗi khi đọc file hình ảnh: {e}")
            return None
    
    def send_image_via_websocket(self, image_path, timestamp, quality="high"):
        """
        Gửi hình ảnh qua WebSocket theo định dạng đơn giản hóa
        
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
            # Chuyển đổi hình ảnh thành base64 (mặc định chất lượng "high")
            image_base64 = self.get_image_as_base64(image_path, quality)
            if not image_base64:
                return False
                
            # Tạo message với cấu trúc đơn giản hóa (không gửi device_id và quality)
            message = {
                'type': 'image',
                'timestamp': timestamp,
                'image_data': image_base64
            }
            
            # Gửi qua WebSocket
            self.ws.send(json.dumps(message))
            logger.info(f"Đã gửi hình ảnh qua WebSocket lúc {timestamp}")
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
        # Cập nhật trạng thái và bắt đầu đo thời gian
        self.processing_status = "Đang chụp ảnh..."
        capture_start_time = time.time()
        
        # Tính khoảng thời gian từ lần chụp trước
        capture_interval = capture_start_time - self.last_capture_time
        self.last_capture_time = capture_start_time
        
        # Chụp ảnh
        image_path = self.capture_photo()
        
        # Đo thời gian chụp ảnh
        self.capture_duration = time.time() - capture_start_time
        
        if not image_path:
            logger.error("Không thể chụp ảnh để gửi đến server")
            self.sent_fail_count += 1
            self.processing_status = "Lỗi chụp ảnh"
            self.current_photo_file = "Không có"
            return False
            
        # Lưu tên file hiện tại
        self.current_photo_file = os.path.basename(image_path)
        
        # Tăng số ảnh đã chụp
        self.total_photos_taken += 1
            
        # Gửi hình ảnh đến server
        _, timestamp = get_timestamp()
        success = False
        
        # Cập nhật trạng thái và bắt đầu đo thời gian gửi
        self.processing_status = "Đang gửi ảnh..."
        send_start_time = time.time()
        
        if self.use_websocket and self.ws_connected:
            # Ưu tiên gửi qua WebSocket nếu có kết nối
            success = self.send_image_via_websocket(image_path, timestamp, quality)
        else:
            # Nếu không có kết nối WebSocket, gửi qua REST API
            success = self.send_image_to_server(image_path, timestamp, quality)
        
        # Đo thời gian gửi ảnh
        self.sending_duration = time.time() - send_start_time
        self.last_sent_time = time.time()
            
        # Cập nhật biến đếm thành công/thất bại và trạng thái
        if success:
            self.sent_success_count += 1
            self.processing_status = "Đã gửi thành công"
            # Cập nhật thời gian cho lần chụp tiếp theo
            self.next_photo_time = time.time() + self.interval
        else:
            self.sent_fail_count += 1
            self.processing_status = "Lỗi gửi ảnh"
            
        return success


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