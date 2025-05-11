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

class VideoStreamManager:
    def __init__(self, video_device="/dev/video0", virtual_device="/dev/video1", 
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
        self.virtual_device = virtual_device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.v4l2_process = None
        self.streaming_process = None
        self.running = False
        # Đăng ký hàm cleanup khi tắt ứng dụng
        atexit.register(self.cleanup)
    
    def setup_v4l2loopback(self):
        """
        Thiết lập v4l2loopback để tạo thiết bị ảo
        """
        try:
            # Kiểm tra xem module v4l2loopback đã được nạp chưa
            result = subprocess.run(["lsmod"], capture_output=True, text=True)
            if "v4l2loopback" not in result.stdout:
                logger.info("Đang nạp module v4l2loopback...")
                subprocess.run(["sudo", "modprobe", "v4l2loopback", "exclusive_caps=1"])
                time.sleep(1)  # Đợi module được nạp
                
            logger.info(f"Thiết bị ảo {self.virtual_device} đã sẵn sàng")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi thiết lập v4l2loopback: {str(e)}")
            return False
    
    def start_video_copying(self):
        """
        Bắt đầu sao chép luồng video từ thiết bị thật sang thiết bị ảo
        """
        if self.v4l2_process:
            return True
            
        logger.info(f"Bắt đầu sao chép video từ {self.video_device} sang {self.virtual_device}")
        
        try:
            # Sử dụng ffmpeg để sao chép từ camera thực sang thiết bị ảo
            command = [
                "ffmpeg", "-f", "v4l2", "-i", self.video_device,
                "-pix_fmt", "yuv420p",
                "-f", "v4l2", self.virtual_device
            ]
            
            self.v4l2_process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(2)  # Đợi để ffmpeg bắt đầu
            
            if self.v4l2_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Không thể sao chép video: {stderr.decode()}")
                self.v4l2_process = None
                return False
                
            logger.info("Video đang được sao chép thành công")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu sao chép video: {str(e)}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False
    
    def start_streaming(self):
        """
        Bắt đầu streaming HLS từ thiết bị ảo
        """
        if self.streaming_process:
            return True
            
        logger.info(f"Bắt đầu streaming HLS từ {self.virtual_device}")
        
        try:
            # Đảm bảo thư mục đầu ra tồn tại
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            
            # Sử dụng GStreamer để tạo HLS stream
            command = [
                "gst-launch-1.0",
                "v4l2src", f"device={self.virtual_device}", "!", 
                f"image/jpeg,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                "jpegdec", "!",
                "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
                "mpegtsmux", "!",
                "hlssink", 
                f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                "target-duration=2", 
                "max-files=3"
            ]
            
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(2)  # Đợi để GStreamer bắt đầu
            
            if self.streaming_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.streaming_process.communicate()
                logger.error(f"Không thể bắt đầu streaming: {stderr.decode()}")
                self.streaming_process = None
                return False
                
            logger.info("Streaming HLS đã bắt đầu thành công")
            
            # Cập nhật trạng thái streaming trên Firebase
            if device_uuid and id_token:
                # Lấy URL ngrok mới (có thể đã thay đổi)
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    # Thêm đường dẫn đến playlist.m3u8
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    # Cập nhật trạng thái online và URI
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    # Không có URL ngrok, chỉ cập nhật trạng thái online
                    update_streaming_status(device_uuid, id_token, True)
            
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu streaming HLS: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False
    
    def start(self):
        """
        Bắt đầu cả hai quá trình: sao chép video và streaming
        """
        if self.running:
            logger.info("Dịch vụ đã đang chạy")
            return True
        
        if not self.setup_v4l2loopback():
            return False
        
        if not self.start_video_copying():
            return False
        
        if not self.start_streaming():
            # Nếu không thể bắt đầu streaming, dừng cả quá trình sao chép video
            self.stop_video_copying()
            return False
        
        self.running = True
        return True
    
    def stop_video_copying(self):
        """Dừng quá trình sao chép video"""
        if self.v4l2_process:
            logger.info("Đang dừng quá trình sao chép video...")
            self.v4l2_process.terminate()
            self.v4l2_process.wait(timeout=5)
            self.v4l2_process = None
    
    def stop_streaming(self):
        """Dừng quá trình streaming HLS"""
        if self.streaming_process:
            logger.info("Đang dừng quá trình streaming HLS...")
            self.streaming_process.terminate()
            self.streaming_process.wait(timeout=5)
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
        """
        Hàm dọn dẹp được gọi khi tắt ứng dụng,
        đảm bảo cập nhật trạng thái offline
        """
        if self.running:
            logger.info("Đang dọn dẹp trước khi tắt...")
            self.stop()

def main():
    """Hàm chính để chạy dịch vụ streaming"""
    global device_uuid, id_token
    
    parser = argparse.ArgumentParser(description='Video streaming với v4l2loopback')
    parser.add_argument('--physical-device', default='/dev/video0', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', default='/dev/video1', help='Thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=640, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=480, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=30, help='Tốc độ khung hình')
    parser.add_argument('--no-firebase', action='store_true', help='Không sử dụng Firebase')
    
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
        manager.stop()

if __name__ == "__main__":
    main()