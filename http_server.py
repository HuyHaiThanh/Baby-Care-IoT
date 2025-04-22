# File: http_server.py
# HTTP Server cho REST API

import os
import json
import datetime
import time
import base64
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from config import SERVER_HOST, SERVER_PORT, DEVICE_NAME, PHOTO_DIR, AUDIO_DIR, ARCHIVE_DIR
from camera_handler import capture_photo
from audio_handler import capture_audio
from audio_analysis import detect_baby_crying

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('http_server')

# Cache lưu trữ dữ liệu mới nhất
latest_data = {
    "photo": None,
    "audio": None,
    "crying_detected": False,
    "last_update": None
}

# Lock cho việc truy cập dữ liệu đồng thời
data_lock = threading.Lock()

def encode_file_to_base64(file_path):
    """Mã hóa file thành dạng base64"""
    try:
        with open(file_path, "rb") as file:
            encoded = base64.b64encode(file.read())
            return encoded.decode('utf-8')
    except Exception as e:
        logger.error(f"Lỗi khi mã hóa file {file_path}: {e}")
        return None

def update_latest_photo(file_path):
    """Cập nhật ảnh mới nhất vào cache"""
    with data_lock:
        base64_data = encode_file_to_base64(file_path)
        if base64_data:
            timestamp = datetime.datetime.now().isoformat()
            latest_data["photo"] = {
                "data": base64_data,
                "timestamp": timestamp,
                "device_name": DEVICE_NAME,
                "file_name": os.path.basename(file_path)
            }
            latest_data["last_update"] = timestamp
            return True
    return False

def update_latest_audio(file_path, is_crying=False):
    """Cập nhật âm thanh mới nhất vào cache"""
    with data_lock:
        base64_data = encode_file_to_base64(file_path)
        if base64_data:
            timestamp = datetime.datetime.now().isoformat()
            latest_data["audio"] = {
                "data": base64_data,
                "timestamp": timestamp,
                "device_name": DEVICE_NAME,
                "file_name": os.path.basename(file_path),
                "is_crying": is_crying
            }
            latest_data["crying_detected"] = is_crying
            latest_data["last_update"] = timestamp
            return True
    return False

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True

class APIHandler(BaseHTTPRequestHandler):
    def _set_headers(self, content_type="application/json", status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')  # Enable CORS
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _handle_options(self):
        """Handle OPTIONS request (pre-flight CORS check)"""
        self._set_headers()
        
    def do_OPTIONS(self):
        """Handle OPTIONS request method"""
        self._handle_options()
        
    def do_GET(self):
        """Xử lý yêu cầu GET"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        # GET /api/status - Trả về trạng thái của thiết bị
        if path == '/api/status':
            with data_lock:
                status_data = {
                    "status": "online",
                    "device_name": DEVICE_NAME,
                    "crying_detected": latest_data["crying_detected"],
                    "last_update": latest_data["last_update"],
                    "has_photo": latest_data["photo"] is not None,
                    "has_audio": latest_data["audio"] is not None
                }
                
            self._set_headers()
            self.wfile.write(json.dumps(status_data).encode())
            
        # GET /api/latest - Trả về dữ liệu mới nhất
        elif path == '/api/latest':
            with data_lock:
                response_data = {
                    "status": "success",
                    "data": {
                        "photo": latest_data["photo"],
                        "audio": latest_data["audio"],
                        "crying_detected": latest_data["crying_detected"],
                        "last_update": latest_data["last_update"],
                        "device_name": DEVICE_NAME
                    }
                }
            
            self._set_headers()
            self.wfile.write(json.dumps(response_data).encode())
            
        # GET /api/photo - Trả về ảnh mới nhất
        elif path == '/api/photo':
            with data_lock:
                if latest_data["photo"]:
                    response_data = {
                        "status": "success",
                        "data": {
                            "photo": latest_data["photo"],
                            "device_name": DEVICE_NAME,
                            "last_update": latest_data["last_update"]
                        }
                    }
                else:
                    response_data = {
                        "status": "error",
                        "message": "Không có dữ liệu ảnh",
                        "device_name": DEVICE_NAME
                    }
            
            self._set_headers()
            self.wfile.write(json.dumps(response_data).encode())
            
        # GET /api/audio - Trả về âm thanh mới nhất
        elif path == '/api/audio':
            with data_lock:
                if latest_data["audio"]:
                    response_data = {
                        "status": "success",
                        "data": {
                            "audio": latest_data["audio"],
                            "crying_detected": latest_data["crying_detected"],
                            "device_name": DEVICE_NAME,
                            "last_update": latest_data["last_update"]
                        }
                    }
                else:
                    response_data = {
                        "status": "error",
                        "message": "Không có dữ liệu âm thanh",
                        "device_name": DEVICE_NAME
                    }
            
            self._set_headers()
            self.wfile.write(json.dumps(response_data).encode())
            
        # GET /api/capture - Chụp ảnh mới
        elif path == '/api/capture':
            photo_path = capture_photo()
            if photo_path and os.path.exists(photo_path):
                update_latest_photo(photo_path)
                self._set_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Captured new photo"}).encode())
            else:
                self._set_headers(status_code=500)
                self.wfile.write(json.dumps({"status": "error", "message": "Failed to capture photo"}).encode())
                
        # GET /api/record - Ghi âm mới
        elif path == '/api/record':
            # Phân tích query parameters
            query_params = parse_qs(parsed_url.query)
            duration = int(query_params.get('duration', [5])[0])  # Mặc định 5 giây
            
            audio_path = capture_audio(duration)
            if audio_path and os.path.exists(audio_path):
                is_crying = detect_baby_crying(audio_path)
                update_latest_audio(audio_path, is_crying)
                self._set_headers()
                self.wfile.write(json.dumps({
                    "status": "success", 
                    "message": "Recorded new audio", 
                    "crying_detected": is_crying
                }).encode())
            else:
                self._set_headers(status_code=500)
                self.wfile.write(json.dumps({"status": "error", "message": "Failed to record audio"}).encode())
        
        else:
            # Đường dẫn không hợp lệ
            self._set_headers(status_code=404)
            self.wfile.write(json.dumps({"status": "error", "message": "Not found"}).encode())

def run_server(server_class=ThreadedHTTPServer, handler_class=APIHandler, host=SERVER_HOST, port=SERVER_PORT):
    """Chạy HTTP server"""
    server_address = (host, port)
    httpd = server_class(server_address, handler_class)
    logger.info(f"Khởi động HTTP server tại http://{host}:{port}")
    logger.info(f"Thiết bị: {DEVICE_NAME}")
    logger.info(f"API endpoints:")
    logger.info(f"  - http://{host}:{port}/api/status")
    logger.info(f"  - http://{host}:{port}/api/latest")
    logger.info(f"  - http://{host}:{port}/api/photo")
    logger.info(f"  - http://{host}:{port}/api/audio")
    logger.info(f"  - http://{host}:{port}/api/capture")
    logger.info(f"  - http://{host}:{port}/api/record")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
        logger.info("HTTP server đã dừng")
    except Exception as e:
        logger.error(f"Lỗi server: {e}")
        httpd.server_close()

# Hàm để chạy HTTP server trong một thread riêng biệt
def start_http_server_in_thread():
    """Chạy HTTP server trong một thread riêng biệt"""
    http_thread = threading.Thread(target=run_server)
    http_thread.daemon = True
    http_thread.start()
    return http_thread

if __name__ == "__main__":
    # Tạo thư mục lưu trữ nếu chưa tồn tại
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    # Khởi động server
    run_server()