#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import logging
import signal
import sys
import time
import socket
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('video_streaming')

HLS_OUTPUT_DIR = "/var/www/html"

# Global variables
gstreamer_process = None
device_uuid = None
id_token = None
running = False

def initialize_firebase():
    """Khởi tạo Firebase và lấy thông tin thiết bị"""
    global device_uuid, id_token
    try:
        logger.info("Đang khởi tạo Firebase...")
        # initialize_device() trả về tuple (device_uuid, id_token)
        device_uuid, id_token = initialize_device()
        if device_uuid and id_token:
            logger.info(f"Thiết bị đã được khởi tạo: {device_uuid}")
            return True
        else:
            logger.error("Không thể khởi tạo Firebase")
            return False
    except Exception as e:
        logger.error(f"Lỗi khởi tạo Firebase: {e}")
        return False

def get_ip_address():
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

def cleanup_old_files():
    """Xóa các file stream cũ trước khi bắt đầu"""
    logger.info("Xóa các file stream cũ...")
    try:
        # Xóa các file .ts và .m3u8 cũ
        subprocess.run([
            "sudo", "find", HLS_OUTPUT_DIR, 
            "-name", "*.ts", "-delete"
        ], check=True)
        subprocess.run([
            "sudo", "find", HLS_OUTPUT_DIR, 
            "-name", "*.m3u8", "-delete"
        ], check=True)
        logger.info("Đã xóa các file stream cũ")
    except Exception as e:
        logger.warning(f"Lỗi xóa file cũ: {e}")

def setup_output_directory():
    """Thiết lập thư mục output cho HLS"""
    try:
        # Tạo thư mục nếu chưa tồn tại
        subprocess.run(["sudo", "mkdir", "-p", HLS_OUTPUT_DIR], check=True)
        
        # Đảm bảo quyền ghi cho thư mục
        subprocess.run(["sudo", "chown", "-R", "www-data:www-data", HLS_OUTPUT_DIR], check=True)
        subprocess.run(["sudo", "chmod", "-R", "755", HLS_OUTPUT_DIR], check=True)
        
        logger.info(f"Thư mục output đã được thiết lập: {HLS_OUTPUT_DIR}")
        return True
    except Exception as e:
        logger.error(f"Lỗi thiết lập thư mục output: {e}")
        return False

def update_firebase_status(is_online):
    """Cập nhật trạng thái streaming trên Firebase"""
    global device_uuid, id_token
    
    if not device_uuid or not id_token:
        logger.warning("Chưa có thông tin thiết bị Firebase")
        return False
        
    try:
        # Lấy URL ngrok nếu có
        ngrok_url = get_ngrok_url()
        
        # Tạo streaming URL
        ip_address = get_ip_address()
        streaming_url = f"http://{ip_address}/playlist.m3u8"
        
        if ngrok_url:
            streaming_url = f"{ngrok_url}/playlist.m3u8"
        
        success = update_streaming_status(
            device_uuid, 
            id_token, 
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

def start_gstreamer():
    """Bắt đầu GStreamer streaming với pipeline chính xác"""
    global gstreamer_process, running
    
    logger.info("Bắt đầu GStreamer HLS streaming...")
    
    # Pipeline GStreamer giống hệt yêu cầu
    cmd = [
        "sudo", "gst-launch-1.0", "-v",
        "v4l2src", "device=/dev/video17", "!",
        "image/jpeg,width=640,height=480,framerate=30/1", "!",
        "jpegdec", "!",
        "videoconvert", "!",
        "x264enc", "tune=zerolatency", "bitrate=64", "speed-preset=ultrafast", "key-int-max=30", "!",
        "h264parse", "!", "mpegtsmux", "!",
        "hlssink", f"location={HLS_OUTPUT_DIR}/segment%05d.ts",
        f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
        "target-duration=5", "max-files=10", "playlist-length=5"
    ]
    
    try:
        logger.info(f"Chạy lệnh: {' '.join(cmd)}")
        gstreamer_process = subprocess.Popen(cmd)
        running = True
        
        # Cập nhật trạng thái online trên Firebase
        update_firebase_status(True)
        
        logger.info("GStreamer đã bắt đầu. HLS stream có sẵn tại /playlist.m3u8")
        return True
    except Exception as e:
        logger.error(f"Lỗi khởi động GStreamer: {e}")
        return False

def stop_streaming():
    """Dừng streaming và cập nhật Firebase"""
    global gstreamer_process, running
    
    if not running:
        return
        
    logger.info("Đang dừng HLS streaming...")
    running = False
    
    # Cập nhật trạng thái offline trên Firebase
    update_firebase_status(False)
    
    if gstreamer_process:
        try:
            gstreamer_process.terminate()
            gstreamer_process.wait(timeout=10)
            logger.info("GStreamer đã dừng")
        except subprocess.TimeoutExpired:
            logger.warning("GStreamer không dừng được, kill process")
            gstreamer_process.kill()
        except Exception as e:
            logger.error(f"Lỗi dừng GStreamer: {e}")
        finally:
            gstreamer_process = None

def signal_handler(signum, frame):
    """Xử lý tín hiệu dừng chương trình"""
    logger.info("Nhận tín hiệu dừng, đang dọn dẹp...")
    stop_streaming()
    sys.exit(0)

def main():
    global gstreamer_process, running
    
    # Đăng ký signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("=== Video Streaming Pipeline ===")
        
        # Bước 1: Khởi tạo Firebase
        if not initialize_firebase():
            logger.error("Không thể khởi tạo Firebase!")
            return 1
        
        # Bước 2: Thiết lập thư mục output
        if not setup_output_directory():
            logger.error("Không thể thiết lập thư mục output!")
            return 1
        
        # Bước 3: Xóa file stream cũ
        cleanup_old_files()
        
        # Bước 4: Bắt đầu GStreamer streaming
        if not start_gstreamer():
            logger.error("Không thể bắt đầu streaming!")
            return 1
        
        # Monitor streaming
        logger.info("HLS streaming đang chạy. Nhấn Ctrl+C để dừng.")
        logger.info(f"Playlist có thể truy cập tại: http://{get_ip_address()}/playlist.m3u8")
        
        # Chờ cho đến khi bị dừng hoặc GStreamer kết thúc
        while running and gstreamer_process and gstreamer_process.poll() is None:
            time.sleep(1)
        
        # Nếu GStreamer kết thúc bất ngờ
        if running and gstreamer_process and gstreamer_process.poll() is not None:
            logger.error(f"GStreamer kết thúc với code: {gstreamer_process.returncode}")
            running = False
            update_firebase_status(False)
            return gstreamer_process.returncode
            
    except KeyboardInterrupt:
        logger.info("Nhận Ctrl+C, đang dừng...")
    except Exception as e:
        logger.error(f"Lỗi chương trình: {e}")
        return 1
    finally:
        stop_streaming()
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
