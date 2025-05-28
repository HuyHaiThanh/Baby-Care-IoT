#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import atexit
import socket
import logging
import signal
import argparse
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('video_streaming')

HLS_OUTPUT_DIR = "/var/www/html"

# Biến toàn cục lưu trữ thông tin thiết bị và token
device_uuid = None
id_token = None

def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logger.warning(f"Không thể lấy địa chỉ IP: {e}")
        return "localhost"

def configure_apache_no_cache():
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
        logger.info("Apache configured no-cache for HLS files")
    except Exception as e:
        logger.error(f"Lỗi khi cấu hình Apache no-cache: {e}")

def find_available_camera_devices():
    """Tìm các thiết bị camera vật lý có sẵn và hoạt động"""
    available_devices = []
    
    if os.path.exists("/dev/video0"):
        try:
            test_cmd = [
                "ffmpeg", "-f", "v4l2", "-hide_banner", "-t", "0.1", 
                "-i", "/dev/video0", "-frames:v", "1", "-f", "null", "-"
            ]
            test_process = subprocess.run(
                test_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=2
            )
            
            if test_process.returncode == 0 or "Immediate exit requested" in test_process.stderr.decode():
                logger.info(f"Tìm thấy thiết bị camera hoạt động: /dev/video0")
                return ["/dev/video0"]
        except Exception as e:
            logger.warning(f"Lỗi khi kiểm tra /dev/video0: {str(e)}")
    
    for i in range(1, 10):
        device = f"/dev/video{i}"
        if os.path.exists(device):
            try:
                test_cmd = ["v4l2-ctl", "--device", device, "--all"]
                test_process = subprocess.run(
                    test_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=2
                )
                
                output = test_process.stdout.decode()
                if "Format Video Capture" in output and "loopback" not in output:
                    logger.info(f"Tìm thấy thiết bị camera hoạt động: {device}")
                    available_devices.append(device)
            except Exception as e:
                logger.debug(f"Lỗi khi kiểm tra {device}: {str(e)}")
    
    if available_devices:
        return available_devices
    
    logger.warning("Không tìm thấy thiết bị camera hoạt động")
    if os.path.exists("/dev/video0"):
        return ["/dev/video0"]
    return []

class VirtualCameraManager:
    def __init__(self, physical_device="/dev/video0", virtual_device="/dev/video17"):
        self.physical_device = physical_device
        # Kiểm tra thiết bị vật lý có tồn tại không
        if not os.path.exists(physical_device):
            available_cameras = find_available_camera_devices()
            if available_cameras:
                self.physical_device = available_cameras[0]
                logger.info(f"Sử dụng camera khả dụng: {self.physical_device}")
            else:
                logger.warning(f"Không tìm thấy camera nào, vẫn sử dụng: {self.physical_device}")
        
        self.virtual_device = virtual_device
        self.ffmpeg_process = None

    def start_copying(self):
        # Giải phóng thiết bị cũ
        subprocess.run(["sudo", "fuser", "-k", self.physical_device, self.virtual_device], capture_output=True)
        time.sleep(2)
        command = [
            "sudo", "ffmpeg",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", "640x480",
            "-framerate", "30",
            "-i", self.physical_device,
            "-c:v", "mjpeg",
            "-f", "v4l2",
            self.virtual_device
        ]
        logger.info("Start copying video from physical to virtual device")
        self.ffmpeg_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(5)
        if self.ffmpeg_process.poll() is not None:
            _, err = self.ffmpeg_process.communicate()
            logger.error(f"ffmpeg copy process failed: {err}")
            self.ffmpeg_process = None
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
            logger.error(f"Error cleaning HLS files: {e}")

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
            time.sleep(10)
            if self.gst_process.poll() is not None:
                stdout, stderr = self.gst_process.communicate()
                logger.error(f"ffmpeg streaming failed: {stderr.decode()}")
                self.gst_process = None
                return False
            if not os.path.exists(f"{HLS_OUTPUT_DIR}/playlist.m3u8"):
                logger.error("Playlist file not created with ffmpeg")
                self.gst_process.terminate()
                self.gst_process = None
                return False
            logger.info(f"Streaming started with ffmpeg at http://{self.ip_address}/playlist.m3u8")
            return True
        except Exception as e:
            logger.error(f"Error with alternative streaming method: {str(e)}")
            if self.gst_process:
                self.gst_process.terminate()
                self.gst_process = None
            return False

    def start(self, source_device):
        """Bắt đầu streaming với thiết bị nguồn được chỉ định"""
        if self.running:
            logger.info("Service is already running")
            return True
            
        if not self.start_streaming(source_device):
            logger.warning("GStreamer failed, trying ffmpeg...")
            if not self.start_streaming_alternative(source_device):
                logger.error("Both streaming methods failed")
                return False
        
        self.running = True
        logger.info("Streaming service started successfully")
        return True

    def stop_streaming(self):
        if self.gst_process:
            logger.info("Stopping streaming process")
            self.gst_process.terminate()
            try:
                self.gst_process.wait(timeout=5)
                logger.info("Streaming process stopped")
            except subprocess.TimeoutExpired:
                logger.warning("Streaming process didn't stop gracefully, killing...")
                self.gst_process.kill()
            self.gst_process = None
            
            # Cập nhật trạng thái Firebase nếu có
            global device_uuid, id_token
            if device_uuid and id_token:
                update_streaming_status(device_uuid, id_token, False)

    def stop(self):
        """Dừng dịch vụ streaming"""
        self.stop_streaming()
        self.clean_hls_files()
        self.running = False
        logger.info("Video streaming service stopped")

    def cleanup(self):
        self.stop()

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
        logger.info("Received keyboard interrupt. Stopping service...")
    finally:
        # Cleanup
        if 'stream' in locals():
            stream.stop()
        if 'vcam' in locals():
            vcam.stop()
        if device_uuid and id_token:
            update_streaming_status(device_uuid, id_token, False)

if __name__ == "__main__":
    main()
