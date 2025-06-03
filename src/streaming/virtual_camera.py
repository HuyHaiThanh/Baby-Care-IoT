#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import logging
import signal
import sys
import time

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('virtual_camera')

# Global variable để xử lý signal
ffmpeg_process = None

def cleanup_devices():
    """Bước 1: Dọn dẹp các thiết bị video"""
    logger.info("Bước 1: Dọn dẹp các thiết bị video...")
    try:
        cmd = ["sudo", "fuser", "-k", "/dev/video0", "/dev/video17"]
        logger.info(f"Chạy lệnh: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.info("Đã dọn dẹp thiết bị video")
        time.sleep(1)
    except Exception as e:
        logger.warning(f"Lỗi khi dọn dẹp: {e}")

def start_ffmpeg():
    """Bước 2: Chạy FFmpeg để tạo virtual camera"""
    global ffmpeg_process
    logger.info("Bước 2: Bắt đầu FFmpeg virtual camera...")
    
    # Lệnh FFmpeg giống hệt pipeline thành công
    cmd = [
        "sudo", "ffmpeg",
        "-f", "v4l2",
        "-input_format", "mjpeg", 
        "-video_size", "640x480",
        "-framerate", "30",
        "-i", "/dev/video0",
        "-c:v", "mjpeg",
        "-f", "v4l2",
        "/dev/video17"
    ]
    
    try:
        logger.info(f"Chạy lệnh: {' '.join(cmd)}")
        ffmpeg_process = subprocess.Popen(cmd)
        logger.info("FFmpeg đã bắt đầu. Virtual camera có sẵn tại /dev/video17")
        return True
    except Exception as e:
        logger.error(f"Lỗi khởi động FFmpeg: {e}")
        return False

def signal_handler(signum, frame):
    """Xử lý tín hiệu dừng chương trình"""
    global ffmpeg_process
    logger.info("Nhận tín hiệu dừng, đang dọn dẹp...")
    
    if ffmpeg_process:
        try:
            ffmpeg_process.terminate()
            ffmpeg_process.wait(timeout=5)
            logger.info("FFmpeg đã dừng")
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg không dừng được, kill process")
            ffmpeg_process.kill()
        except Exception as e:
            logger.error(f"Lỗi dừng FFmpeg: {e}")
    
    sys.exit(0)

def main():
    global ffmpeg_process
    
    # Đăng ký signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("=== Virtual Camera Pipeline ===")
        
        # Bước 1: Cleanup devices
        cleanup_devices()
        
        # Bước 2: Start FFmpeg
        if not start_ffmpeg():
            logger.error("Không thể bắt đầu FFmpeg!")
            return 1
        
        # Chờ FFmpeg chạy
        logger.info("Virtual camera đang chạy. Nhấn Ctrl+C để dừng.")
        
        # Chờ cho đến khi bị dừng hoặc FFmpeg kết thúc
        while ffmpeg_process and ffmpeg_process.poll() is None:
            time.sleep(1)
        
        # Nếu FFmpeg kết thúc bất ngờ
        if ffmpeg_process and ffmpeg_process.poll() is not None:
            logger.error(f"FFmpeg kết thúc với code: {ffmpeg_process.returncode}")
            return ffmpeg_process.returncode
            
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang dừng...")
    except Exception as e:
        logger.error(f"Lỗi chương trình: {e}")
        return 1
    finally:
        signal_handler(None, None)
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
