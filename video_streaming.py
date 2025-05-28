#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import atexit
import socket
import logging
import signal
import sys
import threading
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('video_streaming')

HLS_OUTPUT_DIR = "/var/www/html"

class VideoStreaming:
    def __init__(self, input_device="/dev/video17", output_dir=HLS_OUTPUT_DIR):
        self.input_device = input_device
        self.output_dir = output_dir
        self.gstreamer_process = None
        self.running = False
        self.device_uuid = None
        self.id_token = None
        
    def initialize_firebase(self):
        """Khởi tạo kết nối Firebase và lấy thông tin thiết bị"""
        try:
            logger.info("Đang khởi tạo Firebase...")
            device_info = initialize_device()
            if device_info:
                self.device_uuid = device_info.get('device_uuid')
                self.id_token = device_info.get('id_token')
                logger.info(f"Thiết bị đã được khởi tạo: {self.device_uuid}")
                return True
            else:
                logger.error("Không thể khởi tạo Firebase")
                return False
        except Exception as e:
            logger.error(f"Lỗi khởi tạo Firebase: {e}")
            return False

    def get_ip_address(self):
        """Lấy địa chỉ IP của thiết bị"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            logger.warning(f"Không thể lấy địa chỉ IP: {e}")
            return "localhost"

    def configure_apache_no_cache(self):
        """Cấu hình Apache để không cache các file HLS"""
        apache_config = """
<FilesMatch "\\.(m3u8|ts)$">
    Header set Cache-Control "no-cache, no-store, must-revalidate"
    Header set Pragma "no-cache"
    Header set Expires "0"
</FilesMatch>
"""
        config_path = "/etc/apache2/conf-available/hls-no-cache.conf"
        try:
            with open("/tmp/hls-no-cache.conf", "w") as f:
                f.write(apache_config)
            subprocess.run(["sudo", "mv", "/tmp/hls-no-cache.conf", config_path], check=True)
            subprocess.run(["sudo", "chown", "root:root", config_path], check=True)
            subprocess.run(["sudo", "chmod", "644", config_path], check=True)
            subprocess.run(["sudo", "a2enconf", "hls-no-cache"], check=True)
            subprocess.run(["sudo", "systemctl", "reload", "apache2"], check=True)
            logger.info("Apache đã được cấu hình no-cache cho file HLS")
        except Exception as e:
            logger.error(f"Lỗi cấu hình Apache: {e}")

    def setup_output_directory(self):
        """Thiết lập thư mục output cho HLS"""
        try:
            # Tạo thư mục nếu chưa tồn tại
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Đảm bảo quyền ghi cho thư mục
            subprocess.run(["sudo", "chown", "-R", "www-data:www-data", self.output_dir], check=True)
            subprocess.run(["sudo", "chmod", "-R", "755", self.output_dir], check=True)
            
            logger.info(f"Thư mục output đã được thiết lập: {self.output_dir}")
            return True
        except Exception as e:
            logger.error(f"Lỗi thiết lập thư mục output: {e}")
            return False

    def cleanup_old_files(self):
        """Dọn dẹp các file HLS cũ"""
        try:
            # Xóa các file .ts và .m3u8 cũ
            subprocess.run([
                "sudo", "find", self.output_dir, 
                "-name", "*.ts", "-delete"
            ], check=True)
            subprocess.run([
                "sudo", "find", self.output_dir, 
                "-name", "*.m3u8", "-delete"
            ], check=True)
            logger.info("Đã dọn dẹp các file HLS cũ")
        except Exception as e:
            logger.warning(f"Lỗi dọn dẹp file cũ: {e}")

    def check_input_device(self):
        """Kiểm tra thiết bị video đầu vào"""
        if not os.path.exists(self.input_device):
            logger.error(f"Thiết bị video {self.input_device} không tồn tại!")
            logger.info("Hãy chắc chắn rằng virtual_camera.py đang chạy")
            return False
        
        logger.info(f"Thiết bị video {self.input_device} đã sẵn sàng")
        return True

    def update_firebase_status(self, is_online):
        """Cập nhật trạng thái streaming trên Firebase"""
        if not self.device_uuid or not self.id_token:
            logger.warning("Chưa có thông tin thiết bị Firebase")
            return False
            
        try:
            # Lấy URL ngrok nếu có
            ngrok_url = get_ngrok_url()
            
            # Tạo streaming URL
            ip_address = self.get_ip_address()
            streaming_url = f"http://{ip_address}/playlist.m3u8"
            
            if ngrok_url:
                streaming_url = f"{ngrok_url}/playlist.m3u8"
            
            success = update_streaming_status(
                self.device_uuid, 
                self.id_token, 
                is_online, 
                streaming_url if is_online else None
            )
            
            if success:
                status_text = "ONLINE" if is_online else "OFFLINE"
                logger.info(f"Đã cập nhật trạng thái Firebase: {status_text}")
                if is_online and streaming_url:
                    logger.info(f"Streaming URL: {streaming_url}")
            else:
                logger.error("Không thể cập nhật trạng thái Firebase")
                
            return success
        except Exception as e:
            logger.error(f"Lỗi cập nhật Firebase: {e}")
            return False

    def start_streaming(self):
        """Bắt đầu streaming HLS bằng GStreamer"""
        if self.running:
            logger.warning("Streaming đã đang chạy")
            return False

        logger.info(f"Bắt đầu streaming HLS từ {self.input_device}")
        
        # GStreamer command cho HLS streaming
        gst_cmd = [
            "sudo", "gst-launch-1.0", "-v",
            "v4l2src", f"device={self.input_device}", "!",
            "image/jpeg,width=640,height=480,framerate=30/1", "!",
            "jpegdec", "!",
            "videoconvert", "!",
            "x264enc", "tune=zerolatency", "bitrate=64", "speed-preset=ultrafast", "key-int-max=30", "!",
            "h264parse", "!", "mpegtsmux", "!",
            "hlssink", f"location={self.output_dir}/segment%05d.ts",
            f"playlist-location={self.output_dir}/playlist.m3u8",
            "target-duration=5", "max-files=10", "playlist-length=5"
        ]
        
        try:
            logger.info(f"Chạy lệnh: {' '.join(gst_cmd)}")
            self.gstreamer_process = subprocess.Popen(
                gst_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.running = True
            
            # Cập nhật trạng thái online trên Firebase
            self.update_firebase_status(True)
            
            logger.info("HLS streaming đã bắt đầu")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khởi động GStreamer: {e}")
            return False

    def stop_streaming(self):
        """Dừng streaming"""
        if not self.running:
            return
            
        logger.info("Đang dừng HLS streaming...")
        self.running = False
        
        # Cập nhật trạng thái offline trên Firebase
        self.update_firebase_status(False)
        
        if self.gstreamer_process:
            try:
                self.gstreamer_process.terminate()
                # Chờ process kết thúc
                self.gstreamer_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("GStreamer không dừng được, kill process")
                self.gstreamer_process.kill()
            except Exception as e:
                logger.error(f"Lỗi dừng GStreamer: {e}")
            finally:
                self.gstreamer_process = None
        
        logger.info("HLS streaming đã dừng")

    def monitor_process(self):
        """Monitor GStreamer process"""
        if not self.gstreamer_process:
            return
            
        while self.running and self.gstreamer_process.poll() is None:
            time.sleep(1)
            
        # Nếu process kết thúc bất ngờ
        if self.running and self.gstreamer_process.poll() is not None:
            logger.error("GStreamer process kết thúc bất ngờ")
            self.running = False
            # Cập nhật trạng thái offline
            self.update_firebase_status(False)

def signal_handler(signum, frame):
    """Xử lý tín hiệu dừng chương trình"""
    global video_streaming
    logger.info("Nhận tín hiệu dừng, đang dọn dẹp...")
    if video_streaming:
        video_streaming.stop_streaming()
    sys.exit(0)

def main():
    global video_streaming
    
    # Đăng ký signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Khởi tạo video streaming
    video_streaming = VideoStreaming()
    
    try:
        # Bước 1: Khởi tạo Firebase
        if not video_streaming.initialize_firebase():
            logger.error("Không thể khởi tạo Firebase!")
            return 1
        
        # Bước 2: Cấu hình Apache
        video_streaming.configure_apache_no_cache()
        
        # Bước 3: Thiết lập thư mục output
        if not video_streaming.setup_output_directory():
            logger.error("Không thể thiết lập thư mục output!")
            return 1
        
        # Bước 4: Dọn dẹp file cũ
        video_streaming.cleanup_old_files()
        
        # Bước 5: Kiểm tra thiết bị đầu vào
        if not video_streaming.check_input_device():
            logger.error("Không thể sử dụng thiết bị video đầu vào!")
            logger.info("Hãy chạy virtual_camera.py trước")
            return 1
        
        # Bước 6: Bắt đầu streaming
        if not video_streaming.start_streaming():
            logger.error("Không thể bắt đầu streaming!")
            return 1
        
        # Bước 7: Monitor process
        logger.info("HLS streaming đang chạy. Nhấn Ctrl+C để dừng.")
        logger.info(f"Playlist có thể truy cập tại: http://{video_streaming.get_ip_address()}/playlist.m3u8")
        
        # Tạo thread để monitor GStreamer process
        monitor_thread = threading.Thread(target=video_streaming.monitor_process)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Chờ cho đến khi bị dừng
        while video_streaming.running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang dừng...")
    except Exception as e:
        logger.error(f"Lỗi chương trình: {e}")
    finally:
        video_streaming.stop_streaming()
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
