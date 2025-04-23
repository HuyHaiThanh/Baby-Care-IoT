# File: main.py
# Chương trình chính điều phối các thành phần trên Raspberry Pi 2B

import os
import time
import threading
import signal
import sys
import argparse
import logging
import netifaces
from config import (
    DEVICE_NAME, IMAGE_SERVER_URL, AUDIO_SERVER_URL,
    IMAGE_SERVER_HOST, IMAGE_SERVER_PORT,
    AUDIO_SERVER_HOST, AUDIO_SERVER_PORT,
    PHOTO_INTERVAL, AUDIO_DURATION, AUDIO_SLIDE_SIZE
)
from camera_client import CameraClient
from audio_client import AudioClient
from utils import get_ip_addresses, check_server_status, logger

# Flag để kiểm soát các luồng
running = True
camera_client = None
audio_client = None

def capture_photo_thread():
    """Luồng chụp ảnh định kỳ và gửi đến server"""
    photo_failures = 0
    max_failures = 5
    
    while running:
        try:
            logger.info("\n--- Bắt đầu chu kỳ chụp ảnh mới ---")
            
            if camera_client:
                success = camera_client.capture_and_send_photo()
                
                if success:
                    logger.info(f"Đã chụp và gửi ảnh thành công")
                    photo_failures = 0
                else:
                    logger.warning(f"Không thể chụp hoặc gửi ảnh")
                    photo_failures += 1
            
            # Hiển thị cảnh báo nếu nhiều lỗi liên tiếp
            if photo_failures >= max_failures:
                logger.error("\n===== CHÚ Ý: CAMERA CÓ THỂ KHÔNG HOẠT ĐỘNG =====")
                logger.error("Đã thất bại trong việc chụp ảnh 5 lần liên tiếp.")
                logger.error("Kiểm tra:")
                logger.error(" - Camera đã kết nối đúng cách chưa")
                logger.error(" - Quyền truy cập thiết bị camera (/dev/video0)")
                logger.error(" - Kết nối đến server xử lý hình ảnh")
                logger.error("========================================\n")
                photo_failures = 0
        except Exception as e:
            logger.exception(f"Lỗi trong luồng chụp ảnh: {e}")
            photo_failures += 1
            
        # Chờ đến chu kỳ tiếp theo
        time.sleep(PHOTO_INTERVAL)

def signal_handler(sig, frame):
    """Xử lý khi nhận tín hiệu thoát"""
    global running
    logger.info("\nĐang dừng các luồng...")
    running = False

def check_server_connections():
    """
    Kiểm tra kết nối đến các server
    
    Returns:
        tuple: (image_server_ok, audio_server_ok)
    """
    logger.info("Kiểm tra kết nối đến các server...")
    
    # Kiểm tra server xử lý hình ảnh
    image_server_ok = check_server_status(IMAGE_SERVER_URL)
    if image_server_ok:
        logger.info(f"✓ Server xử lý hình ảnh ({IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}) đang hoạt động")
    else:
        logger.warning(f"✗ Không thể kết nối đến server xử lý hình ảnh ({IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT})")
    
    # Kiểm tra server xử lý âm thanh
    audio_server_ok = check_server_status(AUDIO_SERVER_URL)
    if audio_server_ok:
        logger.info(f"✓ Server xử lý âm thanh ({AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}) đang hoạt động")
    else:
        logger.warning(f"✗ Không thể kết nối đến server xử lý âm thanh ({AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT})")
        
    return image_server_ok, audio_server_ok

def start_monitoring():
    """Khởi động hệ thống giám sát"""
    global running, camera_client, audio_client
    running = True
    
    # Lấy và hiển thị địa chỉ IP
    ip_addresses = get_ip_addresses()
    logger.info("\n" + "="*50)
    logger.info(f"🔌 THÔNG TIN KẾT NỐI CHO THIẾT BỊ {DEVICE_NAME}:")
    if ip_addresses:
        for interface, ip in ip_addresses.items():
            logger.info(f"📱 Địa chỉ IP ({interface}): {ip}")
    else:
        logger.warning("⚠️ Không tìm thấy địa chỉ IP, thiết bị có thể không kết nối mạng!")
    logger.info("="*50 + "\n")
    
    # Kiểm tra kết nối đến các server
    image_server_ok, audio_server_ok = check_server_connections()
    
    # Khởi tạo các client
    if image_server_ok:
        logger.info("Khởi tạo camera client...")
        camera_client = CameraClient(use_websocket=True)
        camera_client.start()
    else:
        logger.warning("Bỏ qua khởi tạo camera client do không kết nối được đến server xử lý hình ảnh")
    
    if audio_server_ok:
        logger.info("Khởi tạo audio client...")
        audio_client = AudioClient(use_websocket=True)
        audio_client.start()
    else:
        logger.warning("Bỏ qua khởi tạo audio client do không kết nối được đến server xử lý âm thanh")
    
    # Khởi động luồng chụp ảnh định kỳ (chỉ khi camera client được khởi tạo thành công)
    if camera_client:
        photo_thread = threading.Thread(target=capture_photo_thread, name="PhotoThread")
        photo_thread.daemon = True
        photo_thread.start()
    
    # Đăng ký handler để bắt tín hiệu thoát
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(f"Đã khởi động hệ thống giám sát em bé - Thiết bị: {DEVICE_NAME}")
    if camera_client:
        logger.info(f"Đang gửi hình ảnh đến server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
    if audio_client:
        logger.info(f"Đang gửi âm thanh đến server: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
    
    # Giữ chương trình chạy
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
        logger.info("Đang dừng chương trình...")
    
    # Dừng các client
    if camera_client:
        camera_client.stop()
    if audio_client:
        audio_client.stop()
    
    logger.info("Hệ thống giám sát đã dừng")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Hệ thống giám sát em bé trên Raspberry Pi 2B')
    parser.add_argument('--mode', choices=['full', 'camera', 'audio'], default='full',
                      help='Chế độ hoạt động: full (mặc định), camera, hoặc audio')
    
    args = parser.parse_args()
    
    # Chọn chế độ chạy
    if args.mode == 'full':
        logger.info("Khởi động ở chế độ đầy đủ (camera + audio)...")
        start_monitoring()
    elif args.mode == 'camera':
        logger.info("Khởi động ở chế độ chỉ camera...")
        # Hiển thị thông tin kết nối
        logger.info(f"Kết nối đến server xử lý hình ảnh: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
        
        # Khởi tạo camera client
        camera_client = CameraClient(use_websocket=True)
        camera_client.start()
        
        # Khởi động luồng chụp ảnh định kỳ
        photo_thread = threading.Thread(target=capture_photo_thread, name="PhotoThread")
        photo_thread.daemon = True
        photo_thread.start()
        
        # Giữ chương trình chạy
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Đang dừng chương trình...")
        finally:
            if camera_client:
                camera_client.stop()
    elif args.mode == 'audio':
        logger.info("Khởi động ở chế độ chỉ audio...")
        # Hiển thị thông tin kết nối
        logger.info(f"Kết nối đến server xử lý âm thanh: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
        
        # Khởi tạo audio client
        audio_client = AudioClient(use_websocket=True)
        audio_client.start()
        
        # Giữ chương trình chạy
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Đang dừng chương trình...")
        finally:
            if audio_client:
                audio_client.stop()
    else:
        logger.error(f"Chế độ không hợp lệ: {args.mode}")