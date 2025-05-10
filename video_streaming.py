#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import signal
import argparse
import logging
import threading
import socket
import re

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('video_streaming')

# Đường dẫn lưu trữ HLS cho Apache/Nginx
HLS_OUTPUT_DIR = "/var/www/html"

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

class VideoStreamManager:
    def __init__(self, video_device="/dev/video0", virtual_device="/dev/video10", 
                 width=640, height=480, framerate=30):
        """
        Khởi tạo quản lý luồng video
        
        Args:
            video_device: Thiết bị camera vật lý
            virtual_device: Thiết bị ảo sẽ được tạo
            width: Chiều rộng video
            height: Chiều cao video
            framerate: Tốc độ khung hình
        """
        self.video_device = video_device
        self.virtual_device = virtual_device  # Sử dụng /dev/video10 để tránh xung đột
        self.width = width
        self.height = height
        self.framerate = framerate
        self.v4l2_process = None
        self.streaming_process = None
        self.running = False
        self.copy_completed = False
        self.copy_lock = threading.Lock()
        self.device_freed = False
        self.ip_address = get_ip_address()
        self.virtual_device_created = False
    
    def setup_v4l2loopback(self):
        """
        Thiết lập v4l2loopback để tạo thiết bị ảo
        """
        try:
            # Đảm bảo đã cài đặt v4l2loopback
            check_installed = subprocess.run(["dpkg", "-s", "v4l2loopback-dkms"], 
                                          capture_output=True, text=True)
            if check_installed.returncode != 0:
                logger.warning("v4l2loopback chưa được cài đặt. Cố gắng cài đặt...")
                subprocess.run(["sudo", "apt-get", "update", "-y"], capture_output=True)
                subprocess.run(["sudo", "apt-get", "install", "-y", "v4l2loopback-dkms"], 
                             capture_output=True)
                time.sleep(2)
            
            # Xóa tất cả các module v4l2loopback hiện tại trước để tránh xung đột
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], 
                           capture_output=True, text=True)
            time.sleep(1)
            
            # Lấy số thiết bị từ đường dẫn, ví dụ: /dev/video10 -> 10
            try:
                device_number = re.search(r'(\d+)$', self.virtual_device).group(1)
            except (AttributeError, IndexError):
                device_number = "10"  # Mặc định là 10 nếu không phân tích được
            
            # Nạp module v4l2loopback với các tùy chọn đúng
            logger.info("Đang nạp module v4l2loopback...")
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
                
            time.sleep(2)  # Đợi module được nạp
            
            # Kiểm tra xem thiết bị đã được tạo chưa
            if not os.path.exists(self.virtual_device):
                logger.error(f"Thiết bị ảo {self.virtual_device} không được tạo thành công")
                return False
            
            # Kiểm tra loại thiết bị để đảm bảo đó là thiết bị v4l2loopback
            try:
                device_info = subprocess.run(["v4l2-ctl", "-d", self.virtual_device, "--all"], 
                                          capture_output=True, text=True)
                if "Driver name" in device_info.stdout and "v4l2loopback" in device_info.stdout:
                    logger.info(f"Thông tin thiết bị ảo:\n{device_info.stdout}")
                    self.virtual_device_created = True
                else:
                    logger.warning(f"Thiết bị {self.virtual_device} không phải là thiết bị v4l2loopback")
                    return False
            except Exception as e:
                logger.error(f"Không thể kiểm tra thông tin thiết bị: {str(e)}")
                return False
                
            logger.info(f"Thiết bị ảo {self.virtual_device} đã được tạo thành công")
            return True
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
            check_busy = subprocess.run(["fuser", "-v", self.video_device], 
                                      capture_output=True, text=True)
            
            if check_busy.returncode == 0:  # Có tiến trình đang sử dụng
                logger.warning(f"Camera {self.video_device} đang được sử dụng bởi tiến trình khác. Thử giải phóng...")
                subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                             capture_output=True, text=True)
                time.sleep(2)  # Đợi giải phóng thiết bị
            
            # Sử dụng ffmpeg để sao chép từ camera thực sang thiết bị ảo
            # Tránh chỉ định input_format để ffmpeg tự phát hiện
            command = [
                "ffmpeg", 
                "-f", "v4l2", 
                "-i", self.video_device,
                "-f", "v4l2", 
                self.virtual_device
            ]
            
            self.v4l2_process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(3)  # Đợi để ffmpeg thiết lập đầy đủ
            
            if self.v4l2_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Không thể sao chép video: {stderr.decode()}")
                self.v4l2_process = None
                
                # Thử phương pháp sao chép thay thế
                return self.start_video_copying_alternative()
            
            # Thiết lập cờ copy_completed và chạy một thread để giải phóng thiết bị vật lý
            # sau một khoảng thời gian ngắn
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
        """
        Phương pháp thay thế để sao chép video sang thiết bị ảo
        """
        logger.info("Thử phương pháp thay thế để sao chép video...")
        
        try:
            # Sử dụng GStreamer thay vì ffmpeg
            command = [
                "gst-launch-1.0", "-v",
                f"v4l2src device={self.video_device} ! videoconvert ! v4l2sink device={self.virtual_device}"
            ]
            
            self.v4l2_process = subprocess.Popen(
                " ".join(command),
                shell=True,
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
        
        # Ưu tiên dùng thiết bị gốc vì thiết bị ảo không hoạt động ổn định với GStreamer
        # Trước tiên giải phóng mọi tiến trình đang sử dụng thiết bị gốc
        logger.info("Bắt đầu streaming HLS từ camera...")
        
        try:
            # Giải phóng thiết bị gốc nếu cần
            subprocess.run(["sudo", "fuser", "-k", self.video_device], 
                         capture_output=True, text=True)
            time.sleep(2)
            
            # Đảm bảo thư mục đầu ra tồn tại và có quyền ghi
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                         capture_output=True, text=True)
            
            # Sử dụng GStreamer với thiết bị gốc và tùy chọn sudo để đảm bảo quyền truy cập
            command = [
                "sudo", "gst-launch-1.0",
                "v4l2src", f"device={self.video_device}", "!", 
                f"image/jpeg,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                "jpegdec", "!",
                "videoconvert", "!",
                "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
                "mpegtsmux", "!",
                "hlssink", 
                f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                "target-duration=2", 
                "max-files=3"
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
                return self.start_streaming_alternative()
            
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu thành công: {stream_url}")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu streaming HLS: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return self.start_streaming_alternative()
    
    def start_streaming_alternative(self):
        """
        Phương pháp thay thế để streaming nếu phương pháp đầu tiên thất bại
        """
        logger.info("Đang thử phương pháp thay thế để streaming với ffmpeg...")
        
        try:
            # Sử dụng ffmpeg thay vì GStreamer
            command = [
                "sudo", "ffmpeg", 
                "-f", "v4l2", 
                "-input_format", "mjpeg",
                "-i", self.video_device, 
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
                stdout, stderr = self.streaming_process.communicate()
                logger.error(f"Phương pháp thay thế cũng thất bại: {stderr.decode()}")
                return False
            
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
        
        # Cố gắng thiết lập v4l2loopback nhưng không bắt buộc thành công
        v4l2_setup_success = self.setup_v4l2loopback()
        
        # Chỉ cố gắng sao chép video nếu thiết lập v4l2loopback thành công
        if v4l2_setup_success:
            self.start_video_copying()
        else:
            logger.warning("Không thể thiết lập v4l2loopback, tiếp tục với thiết bị gốc")
        
        # Streaming là bước quan trọng nhất
        if not self.start_streaming():
            logger.error("Không thể bắt đầu streaming")
            self.stop_video_copying()
            return False
        
        self.running = True
        # Hiển thị URL stream với địa chỉ IP thực
        stream_url = f"http://{self.ip_address}/playlist.m3u8"
        logger.info(f"Dịch vụ đã bắt đầu thành công. HLS stream có sẵn tại {stream_url}")
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
    
    def stop(self):
        """Dừng tất cả các quá trình"""
        self.stop_streaming()
        self.stop_video_copying()
        self.running = False
        logger.info("Dịch vụ đã dừng hoàn toàn")

def main():
    """Hàm chính để chạy dịch vụ streaming"""
    parser = argparse.ArgumentParser(description='Video streaming với v4l2loopback')
    parser.add_argument('--physical-device', default='/dev/video0', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', default='/dev/video10', help='Thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=640, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=480, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=30, help='Tốc độ khung hình')
    parser.add_argument('--direct', action='store_true', help='Stream trực tiếp từ camera vật lý, không dùng virtual device')
    
    args = parser.parse_args()
    
    # Lấy địa chỉ IP để hiển thị URL stream
    ip_address = get_ip_address()
    
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
            logger.info("Bắt đầu streaming trực tiếp từ camera vật lý...")
            command = [
                "sudo", "gst-launch-1.0",
                "v4l2src", f"device={args.physical_device}", "!", 
                f"image/jpeg,width={args.width},height={args.height},framerate={args.framerate}/1", "!",
                "jpegdec", "!",
                "videoconvert", "!",
                "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
                "mpegtsmux", "!",
                "hlssink", 
                f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                "target-duration=2", 
                "max-files=3"
            ]
            
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stream_url = f"http://{ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu. Truy cập tại {stream_url}")
            process.wait()
        else:
            # Sử dụng virtual device để chia sẻ camera
            if manager.start():
                # Không hiển thị URL lần thứ hai vì đã hiển thị trong manager.start()
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

if __name__ == "__main__":
    main()