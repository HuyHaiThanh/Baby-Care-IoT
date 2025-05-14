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
        # Tạo socket và kết nối đến Google DNS để lấy IP cục bộ
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
        # Liệt kê các thiết bị video
        result = subprocess.run(["v4l2-ctl", "--list-devices"], 
                             capture_output=True, text=True)
        
        if result.returncode == 0:
            # Tách thông tin thành các khối thiết bị
            device_blocks = result.stdout.split("\n\n")
            
            for block in device_blocks:
                if not block.strip():
                    continue
                
                # Tìm các đường dẫn thiết bị
                device_paths = re.findall(r'(/dev/video\d+)', block)
                
                for device in device_paths:
                    # Kiểm tra xem đây có phải là thiết bị capture không
                    caps_check = subprocess.run(["v4l2-ctl", "--device", device, "--all"], 
                                            capture_output=True, text=True)
                    
                    if "Format Video Capture" in caps_check.stdout and "loopback" not in caps_check.stdout:
                        available_devices.append(device)
                        logger.info(f"Tìm thấy thiết bị camera: {device}")
            
            if not available_devices:
                # Thử tìm bằng cách đơn giản hơn nếu không tìm thấy
                for i in range(10):  # Thử từ video0 đến video9
                    device = f"/dev/video{i}"
                    if os.path.exists(device):
                        available_devices.append(device)
        else:
            # Nếu v4l2-ctl không hoạt động, thử tìm bằng cách kiểm tra các file thiết bị
            for i in range(10):
                device = f"/dev/video{i}"
                if os.path.exists(device):
                    available_devices.append(device)
    except Exception as e:
        logger.error(f"Lỗi khi tìm thiết bị camera: {str(e)}")
        # Mặc định là video0 nếu có lỗi
        if os.path.exists("/dev/video0"):
            available_devices.append("/dev/video0")
    
    return available_devices

class VideoStreamManager:
    def __init__(self, video_device="/dev/video0", virtual_device="/dev/video10", 
                 width=640, height=360, framerate=25):
        """
        Khởi tạo quản lý luồng video
        
        Args:
            video_device: Thiết bị camera vật lý
            virtual_device: Thiết bị ảo sẽ được tạo
            width: Chiều rộng video
            height: Chiều cao video
            framerate: Tốc độ khung hình
        """
        # Luôn sử dụng thiết bị được chỉ định, mặc định là /dev/video0
        self.video_device = video_device
        self.virtual_device = virtual_device  # Sử dụng /dev/video10 mặc định để tránh xung đột
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
        # Đăng ký hàm cleanup khi tắt ứng dụng
        atexit.register(self.cleanup)
    
    def check_v4l2loopback_installed(self):
        """Kiểm tra xem v4l2loopback đã được cài đặt chưa"""
        try:
            # Kiểm tra xem module có sẵn sàng để nạp không
            check_available = subprocess.run(["modinfo", "v4l2loopback"], 
                                          capture_output=True, text=True)
            if check_available.returncode == 0:
                return True
                
            # Nếu không có sẵn, kiểm tra xem gói có được cài đặt không
            check_installed = subprocess.run(["dpkg", "-s", "v4l2loopback-dkms"], 
                                         capture_output=True, text=True)
            if check_installed.returncode == 0:
                return True
                
            # Cố gắng cài đặt
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
        """Tìm một số thiết bị video khả dụng"""
        for i in range(10, 30):  # Thử từ video10 đến video29
            device_path = f"/dev/video{i}"
            if not os.path.exists(device_path):
                return device_path, i
        return "/dev/video10", 10  # Mặc định nếu không tìm thấy
    
    def setup_v4l2loopback(self):
        """
        Thiết lập v4l2loopback để tạo thiết bị ảo
        """
        try:
            # Kiểm tra xem v4l2loopback đã được cài đặt chưa
            if not self.check_v4l2loopback_installed():
                logger.error("v4l2loopback không được cài đặt. Không thể tiếp tục với thiết bị ảo.")
                return False
            
            # Xóa tất cả các module v4l2loopback hiện tại trước để tránh xung đột
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], 
                           capture_output=True, text=True)
            time.sleep(1)
            
            # Tìm một thiết bị khả dụng
            self.virtual_device, device_number = self.find_available_video_device()
            logger.info(f"Sử dụng thiết bị ảo: {self.virtual_device}")
            
            # Nạp module v4l2loopback với các tùy chọn đúng
            logger.info("Đang nạp module v4l2loopback...")
            cmd = [
                "sudo", "modprobe", "v4l2loopback",
                f"video_nr={device_number}",
                "exclusive_caps=0",  # Đặt 0 để tương thích tốt hơn
                "card_label=\"Virtual Camera\"",
                "max_buffers=2"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Không thể nạp module v4l2loopback: {result.stderr}")
                return False
                
            time.sleep(2)  # Đợi module được nạp
            
            # Kiểm tra xem thiết bị đã được tạo chưa
            if not os.path.exists(self.virtual_device):
                logger.error(f"Thiết bị ảo {self.virtual_device} không được tạo thành công")
                return False
            
            # Kiểm tra loại thiết bị
            try:
                device_info = subprocess.run(["v4l2-ctl", "-d", self.virtual_device, "--info"], 
                                          capture_output=True, text=True)
                
                if "Driver name: v4l2loopback" in device_info.stdout:
                    logger.info(f"Thông tin thiết bị ảo: {device_info.stdout.strip()}")
                    self.virtual_device_created = True
                else:
                    # Thử lấy thông tin chi tiết hơn
                    device_caps = subprocess.run(["v4l2-ctl", "-d", self.virtual_device, "--all"], 
                                            capture_output=True, text=True)
                    logger.info(f"Thông tin thiết bị: {device_caps.stdout.strip()}")
                    
                    if "v4l2loopback" in device_caps.stdout:
                        self.virtual_device_created = True
                        logger.info(f"Thiết bị ảo {self.virtual_device} đã được tạo thành công")
                    else:
                        logger.warning(f"Thiết bị {self.virtual_device} không phải là thiết bị v4l2loopback")
                        return False
            except Exception as e:
                logger.error(f"Không thể kiểm tra thông tin thiết bị: {str(e)}")
                return False
            
            logger.info(f"Thiết bị ảo {self.virtual_device} đã sẵn sàng")
            return self.virtual_device_created
        except Exception as e:
            logger.error(f"Lỗi khi thiết lập v4l2loopback: {str(e)}")
            return False
    
    def free_physical_device(self):
        """
        Giải phóng thiết bị camera vật lý để các tiến trình khác có thể sử dụng
        """
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
            
            # Giải phóng thiết bị vật lý nếu có tiến trình nào đang sử dụng
            try:
                check_busy = subprocess.run(["fuser", "-v", self.video_device], 
                                          capture_output=True, text=True)
                
                if check_busy.returncode == 0:  # Có tiến trình đang sử dụng
                    subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                                 capture_output=True, text=True)
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Lỗi khi giải phóng thiết bị: {str(e)}")
            
            self.device_freed = True
            logger.info(f"Thiết bị vật lý {self.video_device} đã được giải phóng")
    
    def start_video_copying(self):
        """
        Bắt đầu sao chép luồng video từ thiết bị thật sang thiết bị ảo
        """
        if not self.virtual_device_created:
            logger.warning("Không thể sao chép video vì thiết bị ảo không tồn tại")
            return False
            
        if self.v4l2_process:
            return True
            
        logger.info(f"Bắt đầu sao chép video từ {self.video_device} sang {self.virtual_device}")
        
        try:
            # Kiểm tra xem có tiến trình nào đang sử dụng camera không
            try:
                check_busy = subprocess.run(["fuser", "-v", self.video_device], 
                                        capture_output=True, text=True)
                
                if check_busy.returncode == 0:  # Có tiến trình đang sử dụng
                    logger.warning(f"Camera {self.video_device} đang được sử dụng bởi tiến trình khác. Thử giải phóng...")
                    subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                                capture_output=True, text=True)
                    time.sleep(2)  # Đợi giải phóng thiết bị
            except Exception:
                pass  # Bỏ qua nếu không có công cụ fuser
            
            # Sử dụng gst-launch-1.0 với pipeline tương tự để sao chép từ camera thật sang thiết bị ảo
            # Điều này đảm bảo định dạng video giống nhau giữa thiết bị thật và thiết bị ảo
            command = [
                "gst-launch-1.0", "-v",
                f"v4l2src device={self.video_device}", "!",
                f"image/jpeg,width=352,height=288,framerate=25/1", "!",
                "jpegdec", "!",
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
            
            time.sleep(3)  # Đợi để gstreamer thiết lập đầy đủ
            
            if self.v4l2_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Không thể sao chép video: {stderr.decode()}")
                self.v4l2_process = None
                
                # Thử phương pháp sao chép thay thế
                return self.start_video_copying_alternative()
            
            # Thiết lập cờ copy_completed
            self.copy_completed = True
            # Chạy một thread để giải phóng thiết bị vật lý sau 5 giây
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
        """
        Phương pháp thay thế để sao chép video sang thiết bị ảo
        """
        logger.info("Thử phương pháp thay thế để sao chép video...")
        
        try:
            # Sử dụng ffmpeg thay vì GStreamer
            command = [
                "ffmpeg", 
                "-f", "v4l2", 
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", f"{self.framerate}",
                "-i", self.video_device,
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
                # Nếu process đã kết thúc, có lỗi
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
        """
        Bắt đầu streaming HLS từ thiết bị ảo hoặc thiết bị gốc nếu cần
        """
        if self.streaming_process:
            return True
        
        # Ưu tiên dùng thiết bị ảo nếu đã được tạo, nếu không dùng thiết bị gốc
        source_device = self.virtual_device if self.virtual_device_created else self.video_device
        logger.info(f"Bắt đầu streaming HLS từ {source_device}")
        
        try:
            # Đảm bảo thư mục đầu ra tồn tại
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                         capture_output=True, text=True)
            
            # Sử dụng chính xác pipeline được cung cấp
            command = [
                "sudo", "-u", "www-data", "gst-launch-1.0", "-v",
                "v4l2src", f"device={source_device}", "!", 
                f"image/jpeg,width=352,height=288,framerate=25/1", "!",
                "jpegdec", "!",
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
            
            time.sleep(3)  # Đợi để GStreamer bắt đầu
            
            if self.streaming_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.streaming_process.communicate()
                logger.error(f"Không thể bắt đầu streaming: {stderr.decode()}")
                return False
            
            # Cập nhật trạng thái streaming trên Firebase
            if device_uuid and id_token:
                # Lấy URL ngrok mới
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    # Thêm đường dẫn đến playlist.m3u8
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    logger.info(f"Stream URL: {stream_url}")
                    # Cập nhật trạng thái online và URI
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    # Không có URL ngrok, chỉ cập nhật trạng thái online
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
        """
        Phương pháp thay thế để streaming nếu phương pháp đầu tiên thất bại
        """
        logger.info("Đang thử phương pháp thay thế để streaming với ffmpeg...")
        
        try:
            # Sử dụng ffmpeg thay vì GStreamer
            source_device = self.virtual_device if self.virtual_device_created else self.video_device
            
            # Thử với định dạng mjpeg trước
            command = [
                "sudo", "ffmpeg", 
                "-f", "v4l2", 
                "-input_format", "mjpeg",  # Thử với mjpeg
                "-i", source_device, 
                "-c:v", "libx264", 
                "-preset", "ultrafast", 
                "-tune", "zerolatency", 
                "-f", "hls", 
                "-hls_time", "2", 
                "-hls_list_size", "3", 
                "-hls_flags", "delete_segments",
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
                # MJPEG không hoạt động, thử lại không chỉ định định dạng đầu vào
                stdout, stderr = self.streaming_process.communicate()
                logger.warning(f"MJPEG không hoạt động, thử lại không chỉ định định dạng: {stderr.decode()}")
                
                # Phương pháp thay thế không chỉ định định dạng
                command = [
                    "sudo", "ffmpeg", 
                    "-f", "v4l2", 
                    "-i", source_device, 
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-tune", "zerolatency", 
                    "-f", "hls", 
                    "-hls_time", "2", 
                    "-hls_list_size", "3", 
                    "-hls_flags", "delete_segments",
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
            
            # Cập nhật trạng thái streaming trên Firebase
            if device_uuid and id_token:
                # Lấy URL ngrok mới
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
        """
        Bắt đầu quá trình streaming
        """
        if self.running:
            logger.info("Dịch vụ đã đang chạy")
            return True
        
        # Kiểm tra thiết bị camera trước
        if not os.path.exists(self.video_device):
            available_cameras = find_available_camera_devices()
            if available_cameras:
                self.video_device = available_cameras[0]
                logger.info(f"Đã tìm thấy camera khả dụng: {self.video_device}")
            else:
                logger.error(f"Không tìm thấy thiết bị camera nào khả dụng.")
                return False
        
        # Cố gắng thiết lập v4l2loopback nhưng không bắt buộc thành công
        v4l2_setup_success = self.setup_v4l2loopback()
        
        # Chỉ cố gắng sao chép video nếu thiết lập v4l2loopback thành công
        if v4l2_setup_success:
            if self.start_video_copying():
                logger.info("Sao chép video thành công từ camera thật sang thiết bị ảo")
            else:
                logger.warning("Không thể sao chép video sang thiết bị ảo, tiếp tục với thiết bị gốc")
        else:
            logger.warning("Không thể thiết lập v4l2loopback, tiếp tục với thiết bị gốc")
        
        # Streaming là bước quan trọng nhất
        if not self.start_streaming():
            logger.error("Không thể bắt đầu streaming")
            self.stop_video_copying()
            return False
        
        self.running = True
        logger.info("Dịch vụ đã bắt đầu thành công")
        return True
    
    def stop_video_copying(self):
        """Dừng quá trình sao chép video"""
        if self.v4l2_process:
            logger.info("Đang dừng quá trình sao chép video...")
            self.v4l2_process.terminate()
            try:
                self.v4l2_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.v4l2_process.kill()
            self.v4l2_process = None
    
    def stop_streaming(self):
        """Dừng quá trình streaming HLS"""
        if self.streaming_process:
            logger.info("Đang dừng quá trình streaming HLS...")
            self.streaming_process.terminate()
            try:
                self.streaming_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.streaming_process.kill()
            self.streaming_process = None
            
            # Cập nhật trạng thái offline trên Firebase
            if device_uuid and id_token:
                update_streaming_status(device_uuid, id_token, False)
    
    def stop(self):
        """Dừng tất cả các quá trình"""
        self.stop_streaming()
        self.stop_video_copying()
        self.running = False
        logger.info("Dịch vụ đã dừng hoàn toàn")
        
    def cleanup(self):
        """Dọn dẹp khi tắt ứng dụng"""
        self.stop()

def main():
    """Hàm chính để chạy dịch vụ streaming"""
    global device_uuid, id_token
    
    parser = argparse.ArgumentParser(description='Video streaming với v4l2loopback')
    parser.add_argument('--physical-device', default='/dev/video0', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', default='/dev/video10', help='Thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=640, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=480, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=30, help='Tốc độ khung hình')
    parser.add_argument('--no-firebase', action='store_true', help='Không sử dụng Firebase')
    parser.add_argument('--direct', action='store_true', help='Stream trực tiếp từ camera vật lý, không dùng virtual device')
    
    args = parser.parse_args()
    
    # Khởi tạo thiết bị trên Firebase (trừ khi có tùy chọn --no-firebase)
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
    
    # Xử lý tín hiệu kết thúc (Ctrl+C)
    def signal_handler(sig, frame):
        logger.info("Đã nhận tín hiệu ngắt. Đang dừng dịch vụ...")
        manager.stop()
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.direct:
            # Streaming trực tiếp với cấu hình từ câu lệnh đã cung cấp
            logger.info(f"Bắt đầu streaming trực tiếp từ camera vật lý {args.physical_device}...")
            
            # Đảm bảo thư mục đầu ra tồn tại
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                         capture_output=True, text=True)
            
            # Sử dụng chính xác pipeline được cung cấp
            command = [
                "sudo", "-u", "www-data", "gst-launch-1.0", "-v",
                "v4l2src", f"device={args.physical_device}", "!", 
                f"image/jpeg,width=352,height=288,framerate=25/1", "!",
                "jpegdec", "!",
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
            
            # Cập nhật trạng thái streaming trên Firebase nếu streaming thành công
            if streaming_process.poll() is None and not args.no_firebase:
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    update_streaming_status(device_uuid, id_token, True, stream_url)
            
            logger.info("Streaming HLS đã bắt đầu. Nhấn Ctrl+C để dừng.")
            streaming_process.wait()
        else:
            # Sử dụng virtual device để chia sẻ camera
            if manager.start():
                logger.info(f"Dịch vụ đã bắt đầu thành công.")
                
                # Giữ cho chương trình chạy
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