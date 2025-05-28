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
        logger.info("ffmpeg copy process started")
        return True

    def stop_copying(self):
        if self.ffmpeg_process:
            logger.info("Stopping ffmpeg copy process")
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
            self.ffmpeg_process = None

    def start(self):
        """Bắt đầu sao chép video từ camera vật lý sang thiết bị ảo"""
        if self.start_copying():
            return True, self.virtual_device
        else:
            logger.warning("Không thể sao chép video, sử dụng thiết bị vật lý")
            return False, self.physical_device

    def stop(self):
        """Dừng quá trình sao chép video"""
        self.stop_copying()

class VideoStreamManager:
    def __init__(self, device="/dev/video17", width=640, height=480, framerate=30):
        self.device = device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.gst_process = None
        self.ip_address = get_ip_address()
        self.running = False
        configure_apache_no_cache()
        atexit.register(self.cleanup)

    def clean_hls_files(self):
        try:
            subprocess.run(["sudo", "rm", "-f", f"{HLS_OUTPUT_DIR}/segment*.ts", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], capture_output=True)
            logger.info("Deleted old HLS segments and playlist")
        except Exception as e:
            logger.error(f"Lỗi cập nhật Firebase: {e}")
            return False

    def start_streaming(self, source_device):
        subprocess.run(["sudo", "fuser", "-k", source_device], capture_output=True)
        time.sleep(2)
        os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
        subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], check=True)
        subprocess.run(["sudo", "chmod", "-R", "775", HLS_OUTPUT_DIR], check=True)
        self.clean_hls_files()
        
        # Tạo file playlist trống để đảm bảo quyền ghi
        try:
            subprocess.run(["sudo", "touch", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], check=True)
            subprocess.run(["sudo", "chown", "www-data:www-data", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], check=True)
            subprocess.run(["sudo", "chmod", "664", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], check=True)
        except Exception as e:
            logger.warning(f"Could not create initial playlist file: {e}")

        command = [
            "sudo", "-u", "www-data", "gst-launch-1.0", "-v",
            "v4l2src", f"device={source_device}", "!",
            f"image/jpeg,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
            "jpegdec", "!",
            "videoconvert", "!",
            "x264enc", "tune=zerolatency", "bitrate=64", "speed-preset=ultrafast", "key-int-max=30", "!",
            "h264parse", "!",
            "mpegtsmux", "!",
            "hlssink",
            f"location={HLS_OUTPUT_DIR}/segment%05d.ts",
            f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
            "target-duration=5",
            "max-files=10",
            "playlist-length=5"
        ]
        logger.info(f"Start streaming with GStreamer: {' '.join(command)}")
        self.gst_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(10)
        if self.gst_process.poll() is not None:
            _, err = self.gst_process.communicate()
            logger.error(f"GStreamer failed: {err}")
            self.gst_process = None
            return False
        if not os.path.exists(f"{HLS_OUTPUT_DIR}/playlist.m3u8"):
            logger.error("Playlist file not created")
            self.gst_process.terminate()
            self.gst_process = None
            return False
        logger.info(f"Streaming started at http://{self.ip_address}/playlist.m3u8")
        return True

    def start_streaming_alternative(self, source_device):
        """Phương pháp thay thế sử dụng ffmpeg"""
        logger.info("Trying alternative streaming method with ffmpeg...")
        try:
            self.clean_hls_files()
            command = [
                "sudo", "ffmpeg",
                "-f", "v4l2",
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", str(self.framerate),
                "-i", source_device,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-b:v", "64k",
                "-g", "30",
                "-f", "hls",
                "-hls_time", "5",
                "-hls_list_size", "10",
                "-hls_flags", "delete_segments+append_list",
                f"{HLS_OUTPUT_DIR}/playlist.m3u8"
            ]
            logger.info("Using ffmpeg command: " + " ".join(command))
            self.gst_process = subprocess.Popen(
                command,
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
    global device_uuid, id_token
    
    parser = argparse.ArgumentParser(description='Video streaming service')
    parser.add_argument('--physical-device', default='/dev/video0', help='Physical camera device')
    parser.add_argument('--virtual-device', default='/dev/video17', help='Virtual camera device')
    parser.add_argument('--width', type=int, default=640, help='Video width')
    parser.add_argument('--height', type=int, default=480, help='Video height')
    parser.add_argument('--framerate', type=int, default=30, help='Video framerate')
    parser.add_argument('--no-firebase', action='store_true', help='Disable Firebase integration')
    parser.add_argument('--direct', action='store_true', help='Stream directly from physical camera')
    args = parser.parse_args()
    
    # Khởi tạo Firebase nếu được yêu cầu
    if not args.no_firebase:
        logger.info("Initializing Firebase device...")
        device_uuid, id_token = initialize_device()
        if not device_uuid or not id_token:
            logger.warning("Cannot initialize Firebase device. Continuing without Firebase.")
    
    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Stopping service...")
        if 'vcam' in locals():
            vcam.stop()
        if 'stream' in locals():
            stream.stop()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.direct:
            # Stream trực tiếp từ camera vật lý
            logger.info("Starting direct streaming from physical camera")
            stream = VideoStreamManager(width=args.width, height=args.height, framerate=args.framerate)
            
            if not stream.start(args.physical_device):
                logger.error("Cannot start direct streaming")
                exit(1)
            
            # Cập nhật trạng thái Firebase nếu có
            if not args.no_firebase and device_uuid and id_token:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    update_streaming_status(device_uuid, id_token, True, stream_url)
            
            logger.info("Direct streaming started. Press Ctrl+C to stop.")
            while stream.running:
                time.sleep(1)
        else:
            # Sử dụng virtual camera
            logger.info("Starting virtual camera and streaming")
            vcam = VirtualCameraManager(args.physical_device, args.virtual_device)
            success, source_device = vcam.start()
            
            if success:
                logger.info(f"Using virtual device: {source_device}")
            else:
                logger.warning(f"Using physical device: {source_device}")
            
            stream = VideoStreamManager(width=args.width, height=args.height, framerate=args.framerate)
            if not stream.start(source_device):
                logger.error("Cannot start streaming")
                vcam.stop()
                exit(1)
            
            # Cập nhật trạng thái Firebase nếu có
            if not args.no_firebase and device_uuid and id_token:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    update_streaming_status(device_uuid, id_token, True, stream_url)
            
            logger.info("Streaming service started. Press Ctrl+C to stop.")
            while stream.running:
                time.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang dừng...")
    except Exception as e:
        logger.error(f"Lỗi chương trình: {e}")
    finally:
        # Cleanup
        if 'stream' in locals():
            stream.stop()
        if 'vcam' in locals():
            vcam.stop()
        if device_uuid and id_token:
            update_streaming_status(device_uuid, id_token, False)

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
