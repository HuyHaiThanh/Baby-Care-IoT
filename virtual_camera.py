#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import threading
import logging
import signal
import sys

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('virtual_camera')

class VirtualCamera:
    def __init__(self, input_device="/dev/video0", output_device="/dev/video17"):
        self.input_device = input_device
        self.output_device = output_device
        self.ffmpeg_process = None
        self.running = False
        
    def cleanup_devices(self):
        """Dọn dẹp các thiết bị video đang được sử dụng"""
        logger.info("Dọn dẹp các thiết bị video...")
        try:
            # Kill các process đang sử dụng thiết bị
            subprocess.run([
                "sudo", "fuser", "-k", 
                self.input_device, self.output_device
            ], capture_output=True)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Lỗi khi dọn dẹp thiết bị: {e}")

    def check_input_device(self):
        """Kiểm tra thiết bị camera đầu vào"""
        if not os.path.exists(self.input_device):
            logger.error(f"Thiết bị camera {self.input_device} không tồn tại!")
            return False
            
        try:
            # Test camera với ffmpeg
            test_cmd = [
                "ffmpeg", "-f", "v4l2", "-hide_banner", "-t", "0.1",
                "-i", self.input_device, "-frames:v", "1", "-f", "null", "-"
            ]
            result = subprocess.run(
                test_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=5
            )
            
            if result.returncode == 0 or "Immediate exit requested" in result.stderr.decode():
                logger.info(f"Camera {self.input_device} hoạt động bình thường")
                return True
            else:
                logger.error(f"Camera {self.input_device} không hoạt động")
                return False
                
        except Exception as e:
            logger.error(f"Lỗi kiểm tra camera: {e}")
            return False

    def create_virtual_device(self):
        """Tạo thiết bị camera ảo bằng v4l2loopback"""
        try:
            # Kiểm tra xem module v4l2loopback đã được tải chưa
            result = subprocess.run(
                ["lsmod"], 
                capture_output=True, 
                text=True
            )
            
            if "v4l2loopback" not in result.stdout:
                logger.info("Tải module v4l2loopback...")
                subprocess.run([
                    "sudo", "modprobe", "v4l2loopback", 
                    "video_nr=17", "card_label=Virtual Camera"
                ], check=True)
                time.sleep(2)
            
            # Kiểm tra thiết bị ảo đã được tạo chưa
            if os.path.exists(self.output_device):
                logger.info(f"Thiết bị ảo {self.output_device} đã sẵn sàng")
                return True
            else:
                logger.error(f"Không thể tạo thiết bị ảo {self.output_device}")
                return False
                
        except Exception as e:
            logger.error(f"Lỗi tạo thiết bị ảo: {e}")
            return False

    def start_streaming(self):
        """Bắt đầu streaming từ camera thật sang camera ảo"""
        if self.running:
            logger.warning("Streaming đã đang chạy")
            return False

        logger.info(f"Bắt đầu streaming từ {self.input_device} sang {self.output_device}")
        
        # Command FFmpeg để stream từ USB camera sang virtual camera
        ffmpeg_cmd = [
            "sudo", "ffmpeg",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", "640x480",
            "-framerate", "30",
            "-i", self.input_device,
            "-c:v", "mjpeg",
            "-f", "v4l2",
            self.output_device
        ]
        
        try:
            logger.info(f"Chạy lệnh: {' '.join(ffmpeg_cmd)}")
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.running = True
            logger.info("Virtual camera đã bắt đầu streaming")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khởi động FFmpeg: {e}")
            return False

    def stop_streaming(self):
        """Dừng streaming"""
        if not self.running:
            return
            
        logger.info("Đang dừng virtual camera...")
        self.running = False
        
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                # Chờ process kết thúc
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg không dừng được, kill process")
                self.ffmpeg_process.kill()
            except Exception as e:
                logger.error(f"Lỗi dừng FFmpeg: {e}")
            finally:
                self.ffmpeg_process = None
        
        # Dọn dẹp thiết bị
        self.cleanup_devices()
        logger.info("Virtual camera đã dừng")

    def monitor_process(self):
        """Monitor FFmpeg process"""
        if not self.ffmpeg_process:
            return
            
        while self.running and self.ffmpeg_process.poll() is None:
            time.sleep(1)
            
        # Nếu process kết thúc bất ngờ
        if self.running and self.ffmpeg_process.poll() is not None:
            logger.error("FFmpeg process kết thúc bất ngờ")
            self.running = False

def signal_handler(signum, frame):
    """Xử lý tín hiệu dừng chương trình"""
    global virtual_camera
    logger.info("Nhận tín hiệu dừng, đang dọn dẹp...")
    if virtual_camera:
        virtual_camera.stop_streaming()
    sys.exit(0)

def main():
    global virtual_camera
    
    # Đăng ký signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Khởi tạo virtual camera
    virtual_camera = VirtualCamera()
    
    try:
        # Bước 1: Dọn dẹp thiết bị
        virtual_camera.cleanup_devices()
        
        # Bước 2: Kiểm tra camera đầu vào
        if not virtual_camera.check_input_device():
            logger.error("Không thể sử dụng camera đầu vào!")
            return 1
        
        # Bước 3: Tạo thiết bị ảo
        if not virtual_camera.create_virtual_device():
            logger.error("Không thể tạo thiết bị camera ảo!")
            return 1
        
        # Bước 4: Bắt đầu streaming
        if not virtual_camera.start_streaming():
            logger.error("Không thể bắt đầu streaming!")
            return 1
        
        # Bước 5: Monitor process
        logger.info("Virtual camera đang chạy. Nhấn Ctrl+C để dừng.")
        
        # Tạo thread để monitor FFmpeg process
        monitor_thread = threading.Thread(target=virtual_camera.monitor_process)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Chờ cho đến khi bị dừng
        while virtual_camera.running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang dừng...")
    except Exception as e:
        logger.error(f"Lỗi chương trình: {e}")
    finally:
        virtual_camera.stop_streaming()
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
