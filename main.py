# File: main.py
# Tệp chính để chạy client Raspberry Pi cho giám sát trẻ em

import os
import time
import signal
import sys
import argparse

# Chuyển hướng các lỗi ALSA (chạy trước khi import thư viện âm thanh)
# Lưu stderr để có thể khôi phục sau này nếu cần
os.environ['PYTHONUNBUFFERED'] = '1'  # Đảm bảo output không bị buffer
devnull = os.open(os.devnull, os.O_WRONLY)
old_stderr = os.dup(2)
sys.stderr.flush()
os.dup2(devnull, 2)
os.close(devnull)

# Kiểm tra và xử lý lỗi NumPy/SciPy
try:
    # Khôi phục stderr tạm thời để xem lỗi NumPy/SciPy nếu có
    os.dup2(old_stderr, 2)
    import numpy as np
    try:
        import scipy.signal
        # Chuyển hướng stderr lại sau khi import thành công
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except ImportError:
        print("\n❌ Lỗi: Phiên bản NumPy và SciPy không tương thích!")
        print("Vui lòng cài đặt lại các thư viện với phiên bản tương thích:")
        print("\nsudo pip uninstall -y numpy scipy")
        print("sudo apt-get update")
        print("sudo apt-get install -y python3-numpy python3-scipy")
        print("\nHoặc nếu cần phiên bản cụ thể qua pip:")
        print("pip install numpy==1.16.6 scipy==1.2.3\n")
        sys.exit(1)
except ImportError:
    print("\n❌ Lỗi: Không thể import NumPy!")
    print("Vui lòng cài đặt NumPy với:")
    print("\nsudo apt-get update")
    print("sudo apt-get install -y python3-numpy libatlas-base-dev\n")
    sys.exit(1)

# Khôi phục stderr cho các thư viện không liên quan đến âm thanh
# os.dup2(old_stderr, 2)  # Bỏ comment nếu bạn muốn xem tất cả lỗi

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
    
    # Hiển thị thông tin của server
    from config import AUDIO_SERVER_HOST, AUDIO_SERVER_PORT, IMAGE_SERVER_HOST, IMAGE_SERVER_PORT
    print(f"• Server âm thanh: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
    print(f"• Server hình ảnh: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
    
    if camera_client:
        print(f"• Chụp ảnh: mỗi {args.photo_interval} giây")
    
    print("-" * 60)
    print("\nHệ thống đang chạy. Nhấn Ctrl+C để dừng.\n")
    
    # Thêm biến đếm cho việc gửi nhận dữ liệu
    audio_sent_count = 0
    photo_sent_count = 0
    
    # Vòng lặp chính hiển thị trạng thái hệ thống
    try:
        while running:
            # Xóa màn hình để cập nhật thông tin mới (chỉ trong chế độ không phải debug)
            if not args.debug and os.name == 'posix':  # Chỉ trên hệ điều hành giống Unix
                os.system('clear')
                print("\n" + "=" * 60)
                print("HỆ THỐNG GIÁM SÁT TRẺ EM - Raspberry Pi Client")
                print("=" * 60)
            
            # In thông tin trạng thái kết nối và hoạt động
            current_time = time.strftime("%H:%M:%S", time.localtime())
            print(f"\n[{current_time}] Trạng thái hệ thống:")
            
            # Hiển thị thông tin IP server
            from config import AUDIO_SERVER_HOST, AUDIO_SERVER_PORT, IMAGE_SERVER_HOST, IMAGE_SERVER_PORT
            print(f"• Server âm thanh: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
            print(f"• Server hình ảnh: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
            
            # Trạng thái kết nối
            if not args.no_websocket:
                audio_ws_status = "Đã kết nối" if (audio_client and audio_client.ws_connected) else "Đang kết nối..."
                camera_ws_status = "Đã kết nối" if (camera_client and camera_client.ws_connected) else "Đang kết nối..."
                print(f"• WebSocket âm thanh: {audio_ws_status}")
                print(f"• WebSocket hình ảnh: {camera_ws_status}")
            
            # Cập nhật và hiển thị thông tin về âm thanh
            if audio_client:
                audio_status = "Đang ghi âm" if audio_client.is_recording else "Tạm dừng"
                vad_status = "Bật" if audio_client.use_vad_filter else "Tắt"
                
                # Định dạng thời gian xử lý với 1 chữ số thập phân
                proc_time = f"{audio_client.processing_duration:.1f}s"
                proc_interval = f"{audio_client.processing_interval:.1f}s"
                
                print(f"• Âm thanh: {audio_status} | VAD: {vad_status}")
                print(f"  - File hiện tại: {audio_client.current_audio_file}")
                print(f"  - Trạng thái: {audio_client.processing_status}")
                print(f"  - Thời gian xử lý: {proc_time} | Khoảng cách: {proc_interval}")
                print(f"  - Đã xử lý: {audio_client.total_audio_processed} mẫu")
                print(f"  - Đã gửi thành công: {audio_client.sent_success_count} mẫu")
            
            # Cập nhật và hiển thị thông tin về hình ảnh
            if camera_client:
                # Tính thời gian đến lần chụp tiếp theo
                time_to_next = max(0, camera_client.next_photo_time - time.time())
                
                # Định dạng thời gian với 1 chữ số thập phân
                capture_time = f"{camera_client.capture_duration:.1f}s"
                sending_time = f"{camera_client.sending_duration:.1f}s"
                next_in = f"{time_to_next:.1f}s"
                
                print(f"• Hình ảnh: Chụp ảnh mỗi {args.photo_interval}s | Ảnh tiếp theo sau {next_in}")
                print(f"  - File hiện tại: {camera_client.current_photo_file}")
                print(f"  - Trạng thái: {camera_client.processing_status}")
                print(f"  - Thời gian chụp: {capture_time} | Thời gian gửi: {sending_time}")
                print(f"  - Đã chụp: {camera_client.total_photos_taken} ảnh")
                print(f"  - Đã gửi thành công: {camera_client.sent_success_count} ảnh")
            
            # Update status every 5 seconds
            time.sleep(5)
            
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