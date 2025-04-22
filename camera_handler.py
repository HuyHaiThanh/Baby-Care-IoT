# File: camera_handler.py
# Module xử lý chụp ảnh từ camera

import os
import time
import datetime
import subprocess
import re
from config import PHOTO_DIR, TEMP_DIR

# Flag cho việc sử dụng PiCamera hoặc USB camera
PICAMERA_AVAILABLE = False

try:
    from picamera import PiCamera
    PICAMERA_AVAILABLE = True
    print("Đã phát hiện PiCamera.")
except ImportError:
    print("Không tìm thấy PiCamera. Sẽ sử dụng USB camera nếu có.")

def detect_video_devices():
    """Phát hiện và trả về thông tin các thiết bị camera USB"""
    try:
        # Sử dụng lệnh v4l2-ctl để liệt kê các thiết bị video
        proc = subprocess.run(['v4l2-ctl', '--list-devices'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        devices_output = proc.stdout.decode()
        
        if not devices_output.strip():
            # Thử dùng cách khác để liệt kê thiết bị video
            proc = subprocess.run(['ls', '-la', '/dev/video*'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            devices_output = proc.stdout.decode()
            
            if 'No such file or directory' in devices_output:
                return []
                
            # Phân tích đầu ra để tìm thiết bị video
            video_devices = []
            for line in devices_output.splitlines():
                match = re.search(r'/dev/video(\d+)', line)
                if match:
                    video_devices.append({
                        'device': match.group(0),
                        'index': match.group(1),
                        'name': f"Video Device {match.group(1)}"
                    })
            return video_devices
        
        # Phân tích đầu ra của v4l2-ctl
        devices = []
        current_device = None
        for line in devices_output.splitlines():
            if ':' in line and '/dev/video' not in line:
                # Đây là tên thiết bị
                current_device = line.strip().rstrip(':')
            elif '/dev/video' in line:
                # Đây là đường dẫn thiết bị
                match = re.search(r'/dev/video(\d+)', line)
                if match and current_device:
                    devices.append({
                        'device': match.group(0),
                        'index': match.group(1),
                        'name': current_device
                    })
        return devices
    except Exception as e:
        print(f"Lỗi khi phát hiện thiết bị camera: {e}")
        return []

def get_best_video_device():
    """Chọn thiết bị camera phù hợp nhất"""
    devices = detect_video_devices()
    
    if not devices:
        return None
        
    # Ưu tiên USB camera thường có từ camera, webcam, usb trong tên
    for device in devices:
        if 'camera' in device.get('name', '').lower() or 'webcam' in device.get('name', '').lower() or 'usb' in device.get('name', '').lower():
            return device
    
    # Nếu không tìm thấy, chọn thiết bị đầu tiên
    if len(devices) > 0:
        return devices[0]
        
    return None

def capture_with_fswebcam(output_path):
    """Chụp ảnh bằng fswebcam (cho USB camera)"""
    try:
        # Tìm thiết bị camera
        device = get_best_video_device()
        if not device:
            print("Không tìm thấy thiết bị camera USB")
            return None
                
        # Dùng fswebcam để chụp ảnh
        device_path = device['device']
        print(f"Bắt đầu chụp ảnh từ thiết bị {device_path}...")
        
        # Đảm bảo thư mục tạm tồn tại
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        # Đường dẫn đến file tạm
        temp_path = os.path.join(TEMP_DIR, "temp_capture.jpg")
        
        # Chụp ảnh với fswebcam
        subprocess.run([
            'fswebcam',
            '-q',                   # Chế độ im lặng (không hiển thị banner)
            '-r', '1280x720',       # Độ phân giải
            '--no-banner',          # Không hiển thị banner
            '-d', device_path,      # Thiết bị camera
            '--jpeg', '85',         # Chất lượng JPEG
            '-F', '5',              # Số frames để bỏ qua (giúp camera ổn định)
            temp_path               # Đường dẫn file đầu ra
        ], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        
        # Kiểm tra file có được tạo thành công
        if not os.path.exists(temp_path):
            print("Lỗi chụp ảnh - file không được tạo")
            return None
            
        if os.path.getsize(temp_path) < 1000:  # Kiểm tra kích thước tối thiểu
            print("Lỗi chụp ảnh - file quá nhỏ, có thể bị lỗi")
            os.remove(temp_path)
            return None
            
        # Di chuyển file từ thư mục tạm đến thư mục đích
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        os.rename(temp_path, output_path)
        
        print(f"Đã chụp ảnh: {output_path}")
        return output_path
                
    except Exception as e:
        print(f"Lỗi khi chụp ảnh với fswebcam: {e}")
        # Dọn dẹp file tạm nếu có lỗi
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        return None

def capture_with_libcamera(output_path):
    """Chụp ảnh bằng libcamera-still (cho Pi Camera)"""
    try:
        # Đảm bảo thư mục tồn tại
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Sử dụng libcamera-still để chụp ảnh (hỗ trợ Raspberry Pi mới)
        subprocess.run([
            'libcamera-still',
            '-t', '1000',           # Thời gian chờ 1 giây
            '-n',                   # Không hiển thị preview
            '--width', '1280',      # Chiều rộng
            '--height', '720',      # Chiều cao
            '-o', output_path       # Đường dẫn file đầu ra
        ], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        
        # Kiểm tra file có được tạo thành công
        if not os.path.exists(output_path):
            print("Lỗi chụp ảnh với libcamera - file không được tạo")
            return None
            
        if os.path.getsize(output_path) < 1000:  # Kiểm tra kích thước tối thiểu
            print("Lỗi chụp ảnh với libcamera - file quá nhỏ, có thể bị lỗi")
            os.remove(output_path)
            return None
            
        print(f"Đã chụp ảnh với libcamera: {output_path}")
        return output_path
                
    except Exception as e:
        print(f"Lỗi khi chụp ảnh với libcamera: {e}")
        return None

def capture_with_picamera(output_path):
    """Chụp ảnh bằng module PiCamera"""
    try:
        # Đảm bảo thư mục tồn tại
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        camera = PiCamera()
        camera.resolution = (1280, 720)
        
        # Khởi động camera và chờ cân bằng độ sáng
        camera.start_preview()
        time.sleep(2)  # Chờ camera điều chỉnh độ sáng
        
        # Chụp ảnh
        camera.capture(output_path)
        camera.stop_preview()
        camera.close()
        
        print(f"Đã chụp ảnh với PiCamera: {output_path}")
        return output_path
    
    except Exception as e:
        print(f"Lỗi khi chụp ảnh với PiCamera: {e}")
        return None

def capture_photo():
    """
    Chụp ảnh từ camera và lưu vào thư mục chỉ định
    
    Returns:
        str: Đường dẫn đến file ảnh đã chụp, hoặc None nếu thất bại
    """
    # Tạo thư mục nếu chưa tồn tại
    os.makedirs(PHOTO_DIR, exist_ok=True)
    
    # Tạo tên file với timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"photo_{timestamp}.jpg"
    filepath = os.path.join(PHOTO_DIR, filename)
    
    # Thử chụp ảnh bằng các phương pháp khác nhau
    
    # Thử với USB camera trước (fswebcam)
    result = capture_with_fswebcam(filepath)
    if result:
        return result
        
    # Nếu không có USB camera, thử dùng PiCamera
    if PICAMERA_AVAILABLE:
        result = capture_with_picamera(filepath)
        if result:
            return result
    
    # Thử dùng libcamera-still (cho Raspberry Pi OS mới)
    result = capture_with_libcamera(filepath)
    if result:
        return result
        
    print("Không thể chụp ảnh: Không tìm thấy thiết bị camera hỗ trợ")
    return None

# Test module khi chạy trực tiếp
if __name__ == "__main__":
    print("Test chụp ảnh từ camera...")
    
    # Liệt kê các thiết bị video
    print("\nCác thiết bị video đã phát hiện:")
    devices = detect_video_devices()
    for idx, device in enumerate(devices):
        print(f"{idx+1}. {device['name']} - {device['device']}")
    
    # Chụp ảnh
    photo_path = capture_photo()
    
    if photo_path:
        print(f"Đã lưu ảnh tại: {photo_path}")
    else:
        print("Không thể chụp ảnh")