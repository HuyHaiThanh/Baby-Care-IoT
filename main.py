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
    
    # Thời gian bắt đầu chạy hệ thống
    start_time = time.time()
    
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
    
    # Khoảng thời gian cập nhật thông tin (giây)
    # Tăng khoảng thời gian làm mới lên để giảm hiện tượng giật
    update_interval = 1.0  # Cập nhật mỗi 1 giây thay vì 0.5 giây
    
    # Lưu trữ nội dung hiển thị trước đó để tránh việc xóa và in lại màn hình quá thường xuyên
    last_display = ""
    
    # Vòng lặp chính hiển thị trạng thái hệ thống
    try:
        while running:
            # Tính thời gian chạy
            runtime = time.time() - start_time
            hours, remainder = divmod(int(runtime), 3600)
            minutes, seconds = divmod(remainder, 60)
            runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Tạo nội dung hiển thị mới
            current_time = time.strftime("%H:%M:%S", time.localtime())
            
            # Tạo nội dung để hiển thị
            display = []
            display.append("\n" + "=" * 60)
            display.append(f"HỆ THỐNG GIÁM SÁT TRẺ EM - Raspberry Pi Client - Thời gian: {runtime_str}")
            display.append("=" * 60)
            display.append(f"\n[{current_time}] Trạng thái hệ thống:")
            display.append(f"• Server âm thanh: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
            display.append(f"• Server hình ảnh: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
            
            # Thêm thông tin về WebSocket nếu được sử dụng
            if not args.no_websocket:
                audio_ws_status = "Đã kết nối" if (audio_client and audio_client.ws_connected) else "Đang kết nối..."
                camera_ws_status = "Đã kết nối" if (camera_client and camera_client.ws_connected) else "Đang kết nối..."
                display.append(f"• WebSocket âm thanh: {audio_ws_status}")
                display.append(f"• WebSocket hình ảnh: {camera_ws_status}")
            
            # Thêm thông tin về âm thanh nếu module âm thanh đang chạy
            if audio_client:
                audio_status = "Đang ghi âm" if audio_client.is_recording else "Tạm dừng"
                vad_status = "Bật" if audio_client.use_vad_filter else "Tắt"
                
                # Định dạng thời gian xử lý với 1 chữ số thập phân
                proc_time = f"{audio_client.processing_duration:.1f}s"
                proc_interval = f"{audio_client.processing_interval:.1f}s"
                
                display.append(f"• Âm thanh: {audio_status} | VAD: {vad_status}")
                display.append(f"  - File hiện tại: {audio_client.current_audio_file}")
                display.append(f"  - Trạng thái: {audio_client.processing_status}")
                display.append(f"  - Thời gian xử lý: {proc_time} | Khoảng cách: {proc_interval}")
                display.append(f"  - Đã xử lý: {audio_client.total_audio_processed} mẫu")
                display.append(f"  - Đã gửi thành công: {audio_client.sent_success_count} mẫu")
            
            # Thêm thông tin về hình ảnh nếu module camera đang chạy
            if camera_client:
                # Định dạng thời gian với 1 chữ số thập phân
                capture_time = f"{camera_client.capture_duration:.1f}s"
                sending_time = f"{camera_client.sending_duration:.1f}s"
                
                display.append(f"• Hình ảnh: Chụp ảnh mỗi {args.photo_interval}s")
                display.append(f"  - File hiện tại: {camera_client.current_photo_file}")
                display.append(f"  - Trạng thái: {camera_client.processing_status}")
                display.append(f"  - Thời gian chụp: {capture_time} | Thời gian gửi: {sending_time}")
                display.append(f"  - Đã chụp: {camera_client.total_photos_taken} ảnh")
                display.append(f"  - Đã gửi thành công: {camera_client.sent_success_count} ảnh")
            
            # Kết hợp thành một chuỗi để hiển thị
            current_display = "\n".join(display)
            
            # Chỉ xóa và cập nhật màn hình khi nội dung thay đổi
            if current_display != last_display:
                # Xóa màn hình chỉ khi cần thiết và không ở chế độ debug
                if not args.debug:
                    if os.name == 'posix':  # Linux/Mac
                        os.system('clear')
                    elif os.name == 'nt':   # Windows
                        # Sử dụng lệnh cls thông qua cmd.exe để tránh lỗi trên PowerShell
                        os.system('cmd /c cls')
                
                # In nội dung mới
                print(current_display)
                
                # Cập nhật nội dung đã hiển thị
                last_display = current_display
            
            # Ngủ trong khoảng thời gian update_interval
            time.sleep(update_interval)
            
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