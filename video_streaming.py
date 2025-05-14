#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import signal
import argparse
import threading
import logging
import atexit
import socket
import re
import glob
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        logger.warning(f"Không thể lấy địa chỉ IP: {str(e)}")
        return "localhost"

def find_available_camera_devices():
    """Tìm tất cả các thiết bị camera có sẵn"""
    available_devices = []
    try:
        result = subprocess.run(["v4l2-ctl", "--list-devices"], 
                             capture_output=True, text=True)
        if result.returncode == 0:
            device_blocks = result.stdout.split("\n\n")
            for block in device_blocks:
                if not block.strip():
                    continue
                device_paths = re.findall(r'(/dev/video\d+)', block)
                for device in device_paths:
                    caps_check = subprocess.run(["v4l2-ctl", "--device", device, "--all"], 
                                            capture_output=True, text=True)
                    if "Format Video Capture" in caps_check.stdout and "loopback" not in caps_check.stdout:
                        available_devices.append(device)
                        logger.info(f"Tìm thấy thiết bị camera: {device}")
            if not available_devices:
                for i in range(10):
                    device = f"/dev/video{i}"
                    if os.path.exists(device):
                        available_devices.append(device)
        else:
            for i in range(10):
                device = f"/dev/video{i}"
                if os.path.exists(device):
                    available_devices.append(device)
    except Exception as e:
        logger.error(f"Lỗi khi tìm thiết bị camera: {str(e)}")
        if os.path.exists("/dev/video0"):
            available_devices.append("/dev/video0")
    return available_devices

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
        # Ghi file với sudo
        with open("/tmp/hls-no-cache.conf", "w") as f:
            f.write(apache_config)
        subprocess.run(["sudo", "mv", "/tmp/hls-no-cache.conf", config_path], check=True)
        subprocess.run(["sudo", "chown", "root:root", config_path], check=True)
        subprocess.run(["sudo", "chmod", "644", config_path], check=True)
        subprocess.run(["sudo", "a2enconf", "hls-no-cache"], check=True)
        subprocess.run(["sudo", "systemctl", "reload", "apache2"], check=True)
        logger.info("Đã cấu hình Apache2 để vô hiệu hóa cache cho file HLS")
    except Exception as e:
        logger.error(f"Lỗi khi cấu hình Apache2 no-cache: {str(e)}")

class VideoStreamManager:
    def __init__(self, video_device="/dev/video0", virtual_device="/dev/video10", 
                 width=352, height=198, framerate=25):
        self.video_device = video_device
        self.virtual_device = virtual_device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.v4l2_process = None
        self.streaming_process = None
        self.running = False
        self.copy_completed = False
        self.device_freed = False
        self.virtual_device_created = False
        self.ip_address = get_ip_address()
        atexit.register(self.cleanup)
        configure_apache_no_cache()

    def check_v4l2loopback_installed(self):
        try:
            check_available = subprocess.run(["modinfo", "v4l2loopback"], 
                                          capture_output=True, text=True)
            if check_available.returncode == 0:
                return True
            check_installed = subprocess.run(["dpkg", "-s", "v4l2loopback-dkms"], 
                                         capture_output=True, text=True)
            if check_installed.returncode == 0:
                return True
            logger.warning("v4l2loopback chưa được cài đặt. Cố gắng cài đặt...")
            subprocess.run(["sudo", "apt-get", "update", "-y"], capture_output=True)
            install_result = subprocess.run(["sudo", "apt-get", "install", "-y", "v4l2loopback-dkms", "v4l2loopback-utils"], 
                                         capture_output=True, text=True)
            if install_result.returncode == 0:
                logger.info("Đã cài đặt v4l2loopback thành công")
                return True
            else:
                logger.error(f"Không thể cài đặt v4l2loopback: {install_result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra v4l2loopback: {str(e)}")
            return False

    def find_available_video_device(self):
        for i in range(10, 30):
            device_path = f"/dev/video{i}"
            if not os.path.exists(device_path):
                return device_path, i
        return "/dev/video10", 10

    def setup_v4l2loopback(self):
        try:
            if not self.check_v4l2loopback_installed():
                logger.error("v4l2loopback không được cài đặt. Không thể tiếp tục với thiết bị ảo.")
                return False
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], capture_output=True, text=True)
            time.sleep(1)
            self.virtual_device, device_number = self.find_available_video_device()
            logger.info(f"Sử dụng thiết bị ảo: {self.virtual_device}")
            cmd = [
                "sudo", "modprobe", "v4l2loopback",
                f"video_nr={device_number}",
                "exclusive_caps=0",
                "card_label=\"Virtual Camera\"",
                "max_buffers=2"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Không thể nạp module v4l2loopback: {result.stderr}")
                return False
            time.sleep(2)
            if not os.path.exists(self.virtual_device):
                logger.error(f"Thiết bị ảo {self.virtual_device} không được tạo thành công")
                return False
            device_info = subprocess.run(["v4l2-ctl", "-d", self.virtual_device, "--all"], 
                                      capture_output=True, text=True)
            if "v4l2loopback" in device_info.stdout:
                self.virtual_device_created = True
                logger.info(f"Thiết bị ảo {self.virtual_device} đã được tạo thành công")
            else:
                logger.warning(f"Thiết bị {self.virtual_device} không phải là thiết bị v4l2loopback")
                return False
            return self.virtual_device_created
        except Exception as e:
            logger.error(f"Lỗi khi thiết lập v4l2loopback: {str(e)}")
            return False

    def free_physical_device(self):
        if self.copy_completed and not self.device_freed:
            logger.info(f"Đang giải phóng thiết bị vật lý {self.video_device}...")
            if self.v4l2_process:
                logger.info("Dừng tiến trình sao chép video để giải phóng thiết bị vật lý")
                self.v4l2_process.terminate()
                try:
                    self.v4l2_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.v4l2_process.kill()
                self.v4l2_process = None
            try:
                check_busy = subprocess.run(["fuser", "-v", self.video_device], 
                                          capture_output=True, text=True)
                if check_busy.returncode == 0:
                    subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                                 capture_output=True, text=True)
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Lỗi khi giải phóng thiết bị: {str(e)}")
            self.device_freed = True
            logger.info(f"Thiết bị vật lý {self.video_device} đã được giải phóng")

    def clean_hls_files(self):
        """Xóa các file HLS cũ trước khi bắt đầu streaming"""
        try:
            # Xóa file với sudo để tránh lỗi quyền
            subprocess.run(["sudo", "rm", "-f", f"{HLS_OUTPUT_DIR}/segment*.ts"], capture_output=True)
            subprocess.run(["sudo", "rm", "-f", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], capture_output=True)
            logger.info("Đã xóa các file HLS cũ")
        except Exception as e:
            logger.error(f"Lỗi khi xóa file HLS cũ: {str(e)}")

    def start_video_copying(self):
        if not self.virtual_device_created:
            logger.warning("Không thể sao chép video vì thiết bị ảo không tồn tại")
            return False
        if self.v4l2_process:
            return True
        logger.info(f"Bắt đầu sao chép video từ {self.video_device} sang {self.virtual_device}")
        try:
            try:
                check_busy = subprocess.run(["fuser", "-v", self.video_device], 
                                        capture_output=True, text=True)
                if check_busy.returncode == 0:
                    logger.warning(f"Camera {self.video_device} đang được sử dụng. Thử giải phóng...")
                    subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                                capture_output=True, text=True)
                    time.sleep(2)
            except Exception:
                pass
            command = [
                "gst-launch-1.0", "-v",
                f"v4l2src device={self.video_device}", "!",
                f"image/jpeg,width=352,height=288,framerate={self.framerate}/1", "!",
                "jpegdec", "!",
                "videoscale", "!",
                f"video/x-raw,width={self.width},height={self.height}", "!",
                "videoconvert", "!",
                f"v4l2sink device={self.virtual_device}"
            ]
            logger.info("Sử dụng lệnh sao chép: " + " ".join(command))
            self.v4l2_process = subprocess.Popen(
                " ".join(command), 
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)
            if self.v4l2_process.poll() is not None:
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Không thể sao chép video: {stderr.decode()}")
                self.v4l2_process = None
                return self.start_video_copying_alternative()
            self.copy_completed = True
            threading.Timer(5.0, self.free_physical_device).start()
            logger.info("Video đang được sao chép thành công")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu sao chép video: {str(e)}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False

    def start_video_copying_alternative(self):
        logger.info("Thử phương pháp thay thế để sao chép video...")
        try:
            command = [
                "ffmpeg", 
                "-f", "v4l2", 
                "-video_size", "352x288",
                "-framerate", f"{self.framerate}",
                "-i", self.video_device,
                "-vf", f"scale={self.width}:{self.height}",
                "-vcodec", "rawvideo",
                "-pix_fmt", "yuv420p",
                "-f", "v4l2", 
                self.virtual_device
            ]
            logger.info("Sử dụng lệnh ffmpeg: " + " ".join(command))
            self.v4l2_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)
            if self.v4l2_process.poll() is not None:
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Phương pháp sao chép thay thế cũng thất bại: {stderr.decode()}")
                self.v4l2_process = None
                return False
            self.copy_completed = True
            threading.Timer(5.0, self.free_physical_device).start()
            logger.info("Video đang được sao chép thành công với phương pháp thay thế")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi sử dụng phương pháp sao chép thay thế: {str(e)}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False

    def start_streaming(self):
        if self.streaming_process:
            return True
        source_device = self.virtual_device if self.virtual_device_created else self.video_device
        logger.info(f"Bắt đầu streaming HLS từ {source_device}")
        try:
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], capture_output=True)
            subprocess.run(["sudo", "chmod", "-R", "775", HLS_OUTPUT_DIR], capture_output=True)
            self.clean_hls_files()
            command = [
                "sudo", "-u", "www-data", "gst-launch-1.0", "-v",
                "v4l2src", f"device={source_device}", "!", 
                f"image/jpeg,width=352,height=288,framerate={self.framerate}/1", "!",
                "jpegdec", "!",
                "videoscale", "!",
                f"video/x-raw,width={self.width},height={self.height}", "!",
                "videoconvert", "!",
                "x264enc", "tune=zerolatency", "bitrate=128", "speed-preset=ultrafast", "key-int-max=30", "!", 
                "mpegtsmux", "!",
                "hlssink", 
                f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                "target-duration=5", 
                "max-files=10"
            ]
            logger.info("Sử dụng lệnh: " + " ".join(command))
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)
            if self.streaming_process.poll() is not None:
                stdout, stderr = self.streaming_process.communicate()
                logger.error(f"Không thể bắt đầu streaming: {stderr.decode()}")
                return False
            if device_uuid and id_token:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    logger.info(f"Stream URL: {stream_url}")
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    update_streaming_status(device_uuid, id_token, True)
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu thành công: {stream_url}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu streaming HLS: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False

    def start_streaming_alternative(self):
        logger.info("Đang thử phương pháp thay thế để streaming với ffmpeg...")
        try:
            source_device = self.virtual_device if self.virtual_device_created else self.video_device
            self.clean_hls_files()
            command = [
                "sudo", "ffmpeg", 
                "-f", "v4l2", 
                "-input_format", "mjpeg",
                "-video_size", "352x288",
                "-framerate", f"{self.framerate}",
                "-i", source_device, 
                "-vf", f"scale={self.width}:{self.height}",
                "-c:v", "libx264", 
                "-preset", "ultrafast", 
                "-tune", "zerolatency", 
                "-b:v", "128k",
                "-g", "30",
                "-f", "hls", 
                "-hls_time", "5", 
                "-hls_list_size", "10", 
                "-hls_flags", "delete_segments+append_list",
                f"{HLS_OUTPUT_DIR}/playlist.m3u8"
            ]
            logger.info("Sử dụng lệnh ffmpeg: " + " ".join(command))
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)
            if self.streaming_process.poll() is not None:
                stdout, stderr = self.streaming_process.communicate()
                logger.warning(f"MJPEG không hoạt động, thử lại không chỉ định định dạng: {stderr.decode()}")
                command = [
                    "sudo", "ffmpeg", 
                    "-f", "v4l2", 
                    "-video_size", "352x288",
                    "-framerate", f"{self.framerate}",
                    "-i", source_device, 
                    "-vf", f"scale={self.width}:{self.height}",
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-tune", "zerolatency", 
                    "-b:v", "128k",
                    "-g", "30",
                    "-f", "hls", 
                    "-hls_time", "5", 
                    "-hls_list_size", "10", 
                    "-hls_flags", "delete_segments+append_list",
                    f"{HLS_OUTPUT_DIR}/playlist.m3u8"
                ]
                logger.info("Sử dụng lệnh ffmpeg thay thế: " + " ".join(command))
                self.streaming_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                time.sleep(3)
                if self.streaming_process.poll() is not None:
                    stdout, stderr = self.streaming_process.communicate()
                    logger.error(f"Phương pháp thay thế cũng thất bại: {stderr.decode()}")
                    return False
            if device_uuid and id_token:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    logger.info(f"Stream URL: {stream_url}")
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    update_streaming_status(device_uuid, id_token, True)
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu với ffmpeg: {stream_url}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi sử dụng phương pháp thay thế: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False

    def start(self):
        if self.running:
            logger.info("Dịch vụ đã đang chạy")
            return True
        if not os.path.exists(self.video_device):
            available_cameras = find_available_camera_devices()
            if available_cameras:
                self.video_device = available_cameras[0]
                logger.info(f"Đã tìm thấy camera khả dụng: {self.video_device}")
            else:
                logger.error(f"Không tìm thấy thiết bị camera nào khả dụng.")
                return False
        v4l2_setup_success = self.setup_v4l2loopback()
        if v4l2_setup_success:
            if self.start_video_copying():
                logger.info("Sao chép video thành công từ camera thật sang thiết bị ảo")
            else:
                logger.warning("Không thể sao chép video sang thiết bị ảo, tiếp tục với thiết bị gốc")
        else:
            logger.warning("Không thể thiết lập v4l2loopback, tiếp tục với thiết bị gốc")
        if not self.start_streaming():
            logger.error("Không thể bắt đầu streaming")
            self.stop_video_copying()
            return False
        self.running = True
        logger.info("Dịch vụ đã bắt đầu thành công")
        return True

    def stop_video_copying(self):
        if self.v4l2_process:
            logger.info("Đang dừng quá trình sao chép video...")
            self.v4l2_process.terminate()
            try:
                self.v4l2_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.v4l2_process.kill()
            self.v4l2_process = None

    def stop_streaming(self):
        if self.streaming_process:
            logger.info("Đang dừng quá trình streaming HLS...")
            self.streaming_process.terminate()
            try:
                self.streaming_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.streaming_process.kill()
            self.streaming_process = None
            if device_uuid and id_token:
                update_streaming_status(device_uuid, id_token, False)

    def stop(self):
        self.stop_streaming()
        self.stop_video_copying()
        self.clean_hls_files()
        self.running = False
        logger.info("Dịch vụ đã dừng hoàn toàn")

    def cleanup(self):
        self.stop()

def main():
    global device_uuid, id_token
    parser = argparse.ArgumentParser(description='Video streaming với v4l2loopback')
    parser.add_argument('--physical-device', default='/dev/video0', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', default='/dev/video10', help='Thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=352, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=198, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=25, help='Tốc độ khung hình')
    parser.add_argument('--no-firebase', action='store_true', help='Không sử dụng Firebase')
    parser.add_argument('--direct', action='store_true', help='Stream trực tiếp từ camera vật lý')
    args = parser.parse_args()
    if not args.no_firebase:
        logger.info("Đang khởi tạo thiết bị trên Firebase...")
        device_uuid, id_token = initialize_device()
        if not device_uuid or not id_token:
            logger.warning("Không thể khởi tạo thiết bị trên Firebase. Tiếp tục mà không có Firebase.")
    manager = VideoStreamManager(
        video_device=args.physical_device,
        virtual_device=args.virtual_device,
        width=args.width,
        height=args.height,
        framerate=args.framerate
    )
    def signal_handler(sig, frame):
        logger.info("Đã nhận tín hiệu ngắt. Đang dừng dịch vụ...")
        manager.stop()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        if args.direct:
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], capture_output=True)
            subprocess.run(["sudo", "chmod", "-R", "775", HLS_OUTPUT_DIR], capture_output=True)
            manager.clean_hls_files()
            command = [
                "sudo", "-u", "www-data", "gst-launch-1.0", "-v",
                "v4l2src", f"device={args.physical_device}", "!", 
                f"image/jpeg,width=352,height=288,framerate={args.framerate}/1", "!",
                "jpegdec", "!",
                "videoscale", "!",
                f"video/x-raw,width={args.width},height={args.height}", "!",
                "videoconvert", "!",
                "x264enc", "tune=zerolatency", "bitrate=128", "speed-preset=ultrafast", "key-int-max=30", "!", 
                "mpegtsmux", "!",
                "hlssink", 
                f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                "target-duration=5", 
                "max-files=10"
            ]
            streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if streaming_process.poll() is None and not args.no_firebase:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    update_streaming_status(device_uuid, id_token, True, stream_url)
            logger.info("Streaming HLS đã bắt đầu. Nhấn Ctrl+C để dừng.")
            streaming_process.wait()
        else:
            if manager.start():
                logger.info(f"Dịch vụ đã bắt đầu thành công.")
                while manager.running:
                    time.sleep(1)
            else:
                logger.error("Không thể khởi động dịch vụ")
    except KeyboardInterrupt:
        logger.info("Đã nhận ngắt từ bàn phím. Đang dừng dịch vụ...")
    finally:
        if not args.direct:
            manager.stop()
        elif device_uuid and id_token:
            update_streaming_status(device_uuid, id_token, False)

if __name__ == "__main__":
    main()