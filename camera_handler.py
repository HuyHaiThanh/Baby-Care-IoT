# File: camera_handler.py
# Module xử lý camera trên Raspberry Pi

import os
import time
import datetime
from config import PHOTO_DIR, CAMERA_RESOLUTION

# Pi camera flag - set to True when running on Raspberry Pi
PI_CAMERA_AVAILABLE = False

try:
    # Thử import thư viện picamera
    import picamera
    PI_CAMERA_AVAILABLE = True
    print("Đã phát hiện PiCamera.")
except ImportError:
    # Fallback to OpenCV for testing on non-Pi systems
    try:
        import cv2
        print("Sử dụng OpenCV thay thế cho PiCamera.")
    except ImportError:
        print("CẢNH BÁO: Không tìm thấy thư viện camera nào (picamera hoặc OpenCV).")

def capture_photo():
    """
    Chụp ảnh từ camera
    
    Returns:
        str: Đường dẫn tới file ảnh, hoặc None nếu không thành công
    """
    # Tạo thư mục lưu ảnh nếu chưa tồn tại
    os.makedirs(PHOTO_DIR, exist_ok=True)
    
    # Tạo tên file với timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"photo_{timestamp}.jpg"
    filepath = os.path.join(PHOTO_DIR, filename)
    
    try:
        if PI_CAMERA_AVAILABLE:
            # Chụp ảnh sử dụng PiCamera
            with picamera.PiCamera() as camera:
                camera.resolution = CAMERA_RESOLUTION
                camera.start_preview()
                # Camera warmup time
                time.sleep(0.5)
                camera.capture(filepath)
                print(f"Đã chụp ảnh: {filename}")
        else:
            # Fallback sử dụng OpenCV
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("Không thể mở camera")
                return None
                
            # Thiết lập độ phân giải
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
            
            # Chụp ảnh
            ret, frame = cap.read()
            if not ret:
                print("Không thể chụp ảnh")
                cap.release()
                return None
                
            # Lưu ảnh
            cv2.imwrite(filepath, frame)
            cap.release()
            print(f"Đã chụp ảnh: {filename}")
        
        return filepath
    except Exception as e:
        print(f"Lỗi khi chụp ảnh: {e}")
        return None

# Test module khi chạy trực tiếp
if __name__ == "__main__":
    photo_path = capture_photo()
    if photo_path:
        print(f"Đã lưu ảnh tại: {photo_path}")
    else:
        print("Không thể chụp ảnh")