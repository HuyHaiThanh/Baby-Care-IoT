#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import signal
import argparse
import logging
import atexit
import socket
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('video_streaming')

# Đường dẫn lưu trữ HLS
HLS_OUTPUT_DIR = "/var/www/html"

# Biến toàn cục lưu trữ thông tin thiết bị và token
device_uuid = None
id_token = None

def get_ip_address():
    """Lấy địa chỉ IP của Raspberry Pi"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        logger.warning(f"Không thể lấy địa chỉ IP: {e}")
        return "localhost"

def configure_apache_no_cache():
    """Cấu hình Apache2 để vô hiệu hóa cache cho file HLS"""
    try:
        apache_config = """
<FilesMatch "\.(m3u8|ts)$">
    Header set Cache-Control "no-cache, no-store, must-revalidate"
    Header set Pragma "no-cache"
    Header set Expires "0"
</FilesMatch>
"""
        config_path = "/etc/apache2/conf-available/hls-no-cache.conf"
        with open("/tmp/hls-no-cache.conf", "w") as f:
            f.write(apache_config)
        subprocess.run(["sudo", "mv", "/tmp/hls-no-cache.conf", config_path], check=True)
        subprocess.run(["sudo", "chown", "root:root", config_path], check=True)
        subprocess.run(["sudo", "chmod", "644", config_path], check=True)
        subprocess.run(["sudo", "a2enconf", "hls-no-cache"], check=True)
        subprocess.run(["sudo", "systemctl", "reload", "apache2"], check=True)
        logger.info("Đã cấu hình Apache2 để vô hiệu hóa cache cho file HLS")
    except Exception as e:
        logger.error(f"Lỗi khi cấu hình Apache2 no-cache: {e}")

def find_available_camera_devices():
    """Tìm thiết bị camera vật lý có sẵn"""
    for i in range(10):
        device = f"/dev/video{i}"
        if os.path.exists(device):
            try:
                result = subprocess.run(["v4l2-ctl", "--device", device, "--all"],
                                       capture_output=True, text=True, timeout=2)
                if "Format Video Capture" in result.stdout and "loopback" not in result.stdout:
                    logger.info(f"Tìm thấy thiết bị camera: {device}")
                    return device
            except Exception as e:
                logger.debug(f"Lỗi khi kiểm tra {device}: {e}")
    logger.warning("Không tìm thấy thiết bị camera")
    return "/dev/video0" if os.path.exists("/dev/video0") else None

class VirtualCameraManager:
    def __init__(self, physical_device="/dev/video0", virtual_device="/dev/video17"):
        self.physical_device = physical_device if os.path.exists(physical_device) else find_available_camera_devices()
        self.virtual_device = virtual_device
        self.v4l2_process = None
        self.virtual_device_created = False

    def check_v4l2loopback_installed(self):
        """Kiểm tra và cài đặt v4l2loopback nếu cần"""
        try:
            if subprocess.run(["modinfo", "v4l2loopback"], capture_output=True).returncode == 0:
                return True
            logger.info("Cài đặt v4l2loopback...")
            subprocess.run(["sudo", "apt-get", "update", "-y"], capture_output=True)
            result = subprocess.run(["sudo", "apt-get", "install", "-y", "v4l2loopback-dkms", "v4l2loopback-utils"],
                                   capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Đã cài đặt v4l2loopback")
                return True
            logger.error(f"Cài đặt v4l2loopback thất bại: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra v4l2loopback: {e}")
            return False

    def cleanup_existing_devices(self):
        """Dọn dẹp thiết bị ảo và module v4l2loopback"""
        try:
            for i in range(30):
                device = f"/dev/video{i}"
                if os.path.exists(device):
                    result = subprocess.run(["v4l2-ctl", "-d", device, "--info"],
                                           capture_output=True, text=True, timeout=2)
                    if "v4l2loopback" in result.stdout:
                        subprocess.run(["sudo", "fuser", "-k", device], capture_output=True)
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], capture_output=True)
            logger.info("Đã dọn dẹp module v4l2loopback")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Lỗi khi dọn dẹp thiết bị ảo: {e}")
            return False

    def setup_virtual_camera(self):
        """Thiết lập thiết bị ảo v4l2loopback"""
        if not self.check_v4l2loopback_installed():
            return False
        self.cleanup_existing_devices()
        try:
            cmd = ["sudo", "modprobe", "v4l2loopback", "video_nr=17", "exclusive_caps=0", "card_label=VirtualCam", "devices=1"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Nạp module v4l2loopback thất bại: {result.stderr}")
                return False
            time.sleep(3)
            if os.path.exists(self.virtual_device):
                self.virtual_device_created = True
                logger.info(f"Thiết bị ảo {self.virtual_device} đã được tạo")
                return True
            logger.error(f"Không tìm thấy {self.virtual_device}")
            return False
        except Exception as e:
            logger.error(f"Lỗi khi thiết lập v4l2loopback: {e}")
            return False

    def start_video_copying(self):
        """Sao chép video từ thiết bị vật lý sang thiết bị ảo"""
        if not self.virtual_device_created:
            logger.warning("Thiết bị ảo chưa được tạo")
            return False
        try:
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
            logger.info(f"Sao chép video: {' '.join(command)}")
            self.v4l2_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(5)
            if self.v4l2_process.poll() is not None:
                _, stderr = self.v4l2_process.communicate()
                logger.error(f"Sao chép video thất bại: {stderr}")
                self.v4l2_process = None
                return False
            logger.info("Đang sao chép video thành công")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi sao chép video: {e}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False

    def stop_video_copying(self):
        """Dừng sao chép video"""
        if self.v4l2_process:
            logger.info(f"Dừng sao chép video (PID: {self.v4l2_process.pid})")
            try:
                self.v4l2_process.terminate()
                self.v4l2_process.wait(timeout=5)
                logger.info("Đã dừng sao chép video")
            except subprocess.TimeoutExpired:
                self.v4l2_process.kill()
                logger.info("Đã buộc dừng sao chép video")
            except Exception as e:
                logger.error(f"Lỗi khi dừng sao chép video: {e}")
            self.v4l2_process = None

    def start(self):
        if self.setup_virtual_camera() and self.start_video_copying():
            return True, self.virtual_device
        self.stop_video_copying()
        logger.warning(f"Sử dụng thiết bị vật lý: {self.physical_device}")
        return False, self.physical_device

    def stop(self):
        self.stop_video_copying()
        self.cleanup_existing_devices()
        logger.info("Đã dừng VirtualCameraManager")

class VideoStreamManager:
    def __init__(self, physical_device="/dev/video0", virtual_device="/dev/video17", width=640, height=480, framerate=30):
        self.physical_device = physical_device
        self.virtual_device = virtual_device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.streaming_process = None
        self.running = False
        self.ip_address = get_ip_address()
        self.virtual_camera_manager = VirtualCameraManager(physical_device, virtual_device)
        atexit.register(self.cleanup)
        configure_apache_no_cache()

    def clean_hls_files(self):
        """Xóa các file HLS cũ"""
        try:
            subprocess.run(["sudo", "rm", "-f", f"{HLS_OUTPUT_DIR}/segment*.ts", f"{HLS_OUTPUT_DIR}/playlist.m3u8"],
                           capture_output=True)
            logger.info("Đã xóa các file HLS cũ")
        except Exception as e:
            logger.error(f"Lỗi khi xóa file HLS: {e}")

    def start_streaming(self, source_device):
        """Bắt đầu streaming với GStreamer"""
        try:
            subprocess.run(["sudo", "fuser", "-k", source_device], capture_output=True)
            time.sleep(3)
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], check=True)
            subprocess.run(["sudo", "chmod", "-R", "775", HLS_OUTPUT_DIR], check=True)
            self.clean_hls_files()
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
                "max-files=10"
            ]
            logger.info(f"Streaming GStreamer: {' '.join(command)}")
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(10)
            if self.streaming_process.poll() is not None:
                _, stderr = self.streaming_process.communicate()
                logger.error(f"GStreamer thất bại: {stderr}")
                self.streaming_process = None
                return False
            if not os.path.exists(f"{HLS_OUTPUT_DIR}/playlist.m3u8"):
                logger.error("Không tạo được playlist.m3u8")
                self.streaming_process.terminate()
                self.streaming_process = None
                return False
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS bắt đầu: {stream_url}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi streaming GStreamer: {e}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False

    def start_streaming_alternative(self, source_device):
        """Bắt đầu streaming với FFmpeg"""
        try:
            subprocess.run(["sudo", "fuser", "-k", source_device], capture_output=True)
            time.sleep(3)
            self.clean_hls_files()
            command = [
                "sudo", "ffmpeg",
                "-f", "v4l2",
                "-input_format", "mjpeg",
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", f"{self.framerate}",
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
            logger.info(f"Streaming FFmpeg: {' '.join(command)}")
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(10)
            if self.streaming_process.poll() is not None:
                _, stderr = self.streaming_process.communicate()
                logger.error(f"FFmpeg thất bại: {stderr}")
                self.streaming_process = None
                return False
            if not os.path.exists(f"{HLS_OUTPUT_DIR}/playlist.m3u8"):
                logger.error("Không tạo được playlist.m3u8")
                self.streaming_process.terminate()
                self.streaming_process = None
                return False
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS bắt đầu: {stream_url}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi streaming FFmpeg: {e}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False

    def start(self):
        if self.running:
            logger.info("Dịch vụ đang chạy")
            return True
        if not os.path.exists(self.physical_device):
            self.physical_device = find_available_camera_devices()
            if not self.physical_device:
                logger.error("Không tìm thấy thiết bị camera")
                return False
        success, source_device = self.virtual_camera_manager.start()
        if success:
            logger.info(f"Sử dụng thiết bị ảo: {source_device}")
        else:
            logger.warning(f"Sử dụng thiết bị vật lý: {source_device}")
        if not self.start_streaming(source_device) and not self.start_streaming_alternative(source_device):
            logger.error("Không thể bắt đầu streaming")
            self.virtual_camera_manager.stop()
            return False
        self.running = True
        logger.info("Dịch vụ bắt đầu thành công")
        return True

    def stop_streaming(self):
        if self.streaming_process:
            logger.info(f"Dừng streaming (PID: {self.streaming_process.pid})")
            try:
                self.streaming_process.terminate()
                self.streaming_process.wait(timeout=10)
                logger.info("Đã dừng streaming")
            except subprocess.TimeoutExpired:
                self.streaming_process.kill()
                logger.info("Đã buộc dừng streaming")
            except Exception as e:
                logger.error(f"Lỗi khi dừng streaming: {e}")
            self.streaming_process = None
            if device_uuid and id_token:
                update_streaming_status(device_uuid, id_token, False)

    def stop(self):
        self.stop_streaming()
        self.virtual_camera_manager.stop()
        self.clean_hls_files()
        self.running = False
        logger.info("Dịch vụ VideoStreamManager dừng hoàn toàn")

    def cleanup(self):
        self.stop()

def main():
    global device_uuid, id_token
    parser = argparse.ArgumentParser(description='Video streaming với v4l2loopback')
    parser.add_argument('--physical-device', default='/dev/video0', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', default='/dev/video17', help='Thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=640, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=480, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=30, help='Tốc độ khung hình')
    parser.add_argument('--no-firebase', action='store_true', help='Không sử dụng Firebase')
    parser.add_argument('--direct', action='store_true', help='Stream trực tiếp từ camera vật lý')
    args = parser.parse_args()

    if not args.no_firebase:
        logger.info("Khởi tạo Firebase...")
        device_uuid, id_token = initialize_device()
        if not device_uuid or not id_token:
            logger.warning("Không thể khởi tạo Firebase")

    manager = VideoStreamManager(
        physical_device=args.physical_device,
        virtual_device=args.virtual_device,
        width=args.width,
        height=args.height,
        framerate=args.framerate
    )

    def signal_handler(sig, frame):
        logger.info("Nhận tín hiệu ngắt. Dừng dịch vụ...")
        manager.stop()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.direct:
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], check=True)
            subprocess.run(["sudo", "chmod", "-R", "775", HLS_OUTPUT_DIR], check=True)
            manager.clean_hls_files()
            subprocess.run(["sudo", "fuser", "-k", args.physical_device], capture_output=True)
            time.sleep(2)
            subprocess.run(["sudo", "modprobe", "-r", "uvcvideo"], capture_output=True)
            time.sleep(1)
            subprocess.run(["sudo", "modprobe", "uvcvideo"], capture_output=True)
            command = [
                "sudo", "-u", "www-data", "ffmpeg",
                "-f", "v4l2",
                "-input_format", "mjpeg",
                "-video_size", f"{args.width}x{args.height}",
                "-framerate", f"{args.framerate}",
                "-i", args.physical_device,
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
            logger.info(f"Streaming trực tiếp: {' '.join(command)}")
            streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(15)
            if streaming_process.poll() is not None:
                _, stderr = streaming_process.communicate()
                logger.error(f"Streaming trực tiếp thất bại: {stderr}")
            elif not os.path.exists(f"{HLS_OUTPUT_DIR}/playlist.m3u8"):
                logger.error("Không tạo được playlist.m3u8")
                streaming_process.terminate()
            else:
                if not args.no_firebase:
                    ngrok_url = get_ngrok_url()
                    if ngrok_url:
                        stream_url = f"{ngrok_url}/playlist.m3u8"
                        update_streaming_status(device_uuid, id_token, True, stream_url)
                logger.info("Streaming HLS bắt đầu. Nhấn Ctrl+C để dừng")
                streaming_process.wait()
        else:
            if manager.start():
                logger.info("Dịch vụ bắt đầu thành công")
                while manager.running:
                    time.sleep(1)
            else:
                logger.error("Không thể khởi động dịch vụ")
    except KeyboardInterrupt:
        logger.info("Nhận ngắt từ bàn phím. Dừng dịch vụ...")
    finally:
        manager.stop()

if __name__ == "__main__":
    main()