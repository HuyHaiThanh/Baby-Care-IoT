# File: main.py
# Tệp chính để chạy client Raspberry Pi cho giám sát trẻ em

import os
import time
import signal
import sys
import argparse
from audio_client import AudioClient
from camera_client import CameraClient
from utils import logger

# Flag để kiểm soát việc thoát chương trình
running = True

def signal_handler(sig, frame):
    """Xử lý tín hiệu tắt từ hệ thống."""
    global running
    print("\nĐang dừng hệ thống...")
    running = False

def parse_arguments():
    """Xử lý tham số dòng lệnh"""
    parser = argparse.ArgumentParser(description='Raspberry Pi client cho hệ thống giám sát trẻ em')
    
    parser.add_argument('--no-audio', action='store_true', help='Tắt chức năng ghi âm')
    parser.add_argument('--no-camera', action='store_true', help='Tắt chức năng camera')
    parser.add_argument('--no-websocket', action='store_true', help='Chỉ sử dụng REST API (không WebSocket)')
    parser.add_argument('--photo-interval', type=int, default=5, help='Khoảng thời gian giữa các lần chụp ảnh (giây)')
    parser.add_argument('--debug', action='store_true', help='Bật chế độ debug')
    
    return parser.parse_args()

def main():
    """Hàm chính khởi động chương trình"""
    # Đăng ký xử lý tín hiệu cho việc tắt chương trình
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Xử lý tham số dòng lệnh
    args = parse_arguments()
    
    # In thông tin khởi động
    print("\n" + "=" * 60)
    print("HỆ THỐNG GIÁM SÁT TRẺ EM - Raspberry Pi Client")
    print("=" * 60)
    
    # Khởi tạo các client
    audio_client = None
    camera_client = None
    
    # Khởi động AudioClient nếu không bị tắt qua tham số
    if not args.no_audio:
        print("\n>> Khởi động module xử lý âm thanh...")
        audio_client = AudioClient(use_websocket=not args.no_websocket)
        if audio_client.start():
            print("✓ Module âm thanh đã khởi động thành công")
        else:
            print("✗ Không thể khởi động module âm thanh")
            audio_client = None
    
    # Khởi động CameraClient nếu không bị tắt qua tham số
    if not args.no_camera:
        print("\n>> Khởi động module xử lý hình ảnh...")
        camera_client = CameraClient(
            use_websocket=not args.no_websocket,
            interval=args.photo_interval
        )
        if camera_client.start():
            print("✓ Module hình ảnh đã khởi động thành công")
        else:
            print("✗ Không thể khởi động module hình ảnh")
            camera_client = None
    
    if not audio_client and not camera_client:
        print("\n❌ Lỗi: Không thể khởi động bất kỳ module nào. Chương trình sẽ thoát.")
        return
    
    # In thông tin về các module đã khởi động
    print("\n" + "-" * 60)
    print("Thông tin hệ thống:")
    print(f"• Chế độ audio: {'Đang chạy' if audio_client else 'Đã tắt'}")
    print(f"• Chế độ camera: {'Đang chạy' if camera_client else 'Đã tắt'}")
    print(f"• Phương thức kết nối: {'REST API' if args.no_websocket else 'WebSocket'}")
    if camera_client:
        print(f"• Chụp ảnh: mỗi {args.photo_interval} giây")
    print("-" * 60)
    print("\nHệ thống đang chạy. Nhấn Ctrl+C để dừng.\n")
    
    # Vòng lặp chính
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu dừng từ người dùng")
    finally:
        # Dừng các client
        print("\nĐang dừng hệ thống...")
        
        if audio_client:
            print(">> Dừng module âm thanh...")
            audio_client.stop()
            
        if camera_client:
            print(">> Dừng module hình ảnh...")
            camera_client.stop()
            
        print("\n✓ Hệ thống đã dừng an toàn")

if __name__ == "__main__":
    main()