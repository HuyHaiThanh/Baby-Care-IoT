# File: main.py
# Chương trình chính chạy trên Raspberry Pi

import os
import time
import datetime
import threading
import signal
import sys
import argparse
import logging
import queue

# Import các module tự viết
from config import PHOTO_INTERVAL, AUDIO_DURATION, ARCHIVE_DIR, DEVICE_NAME, AUDIO_DIR
from camera_handler import capture_photo
from audio_handler import AudioRecorder  # Sử dụng AudioRecorder thay vì capture_audio
from audio_analysis import detect_baby_crying
from http_server import update_latest_photo, update_latest_audio, start_http_server_in_thread
from websocket_server import start_websocket_server_in_thread

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('main')

# Flag để kiểm soát các luồng
running = True
audio_recorder = None
crying_event = threading.Event()  # Sự kiện để thông báo khi phát hiện tiếng khóc
crying_queue = queue.Queue(maxsize=10)  # Hàng đợi cho các đoạn âm thanh có tiếng khóc

def capture_photo_thread():
    """Luồng chụp ảnh định kỳ"""
    photo_failures = 0
    max_failures = 5
    
    while running:
        try:
            logger.info("\n--- Bắt đầu chu kỳ chụp ảnh mới ---")
            photo_path = capture_photo()
            
            if photo_path:
                # Kiểm tra file có tồn tại và không rỗng
                if os.path.exists(photo_path) and os.path.getsize(photo_path) > 0:
                    # Cập nhật vào server
                    update_status = update_latest_photo(photo_path)
                    if update_status:
                        logger.info(f"Đã cập nhật ảnh mới: {os.path.basename(photo_path)}")
                        # Lưu file vào archive sau khi cập nhật
                        archive_path = os.path.join(ARCHIVE_DIR, os.path.basename(photo_path))
                        os.makedirs(ARCHIVE_DIR, exist_ok=True)
                        os.rename(photo_path, archive_path)
                    else:
                        logger.error(f"Lỗi khi cập nhật ảnh: {os.path.basename(photo_path)}")
                    photo_failures = 0
                else:
                    logger.warning(f"Bỏ qua file ảnh không tồn tại hoặc rỗng: {photo_path}")
                    photo_failures += 1
            else:
                logger.warning("Không nhận được đường dẫn ảnh từ hàm chụp ảnh")
                photo_failures += 1
                
            # Hiển thị cảnh báo nếu nhiều lỗi liên tiếp
            if photo_failures >= max_failures:
                logger.error("\n===== CHÚ Ý: CAMERA CÓ THỂ KHÔNG HOẠT ĐỘNG =====")
                logger.error("Đã thất bại trong việc chụp ảnh 5 lần liên tiếp.")
                logger.error("Kiểm tra:")
                logger.error(" - Camera đã kết nối đúng cách chưa")
                logger.error(" - Quyền truy cập thiết bị camera (/dev/video0)")
                logger.error("========================================\n")
                photo_failures = 0
        except Exception as e:
            logger.exception(f"Lỗi trong luồng chụp ảnh: {e}")
            photo_failures += 1
            
        # Chờ đến chu kỳ tiếp theo
        time.sleep(PHOTO_INTERVAL)

def process_audio_chunk(audio_data, chunk_id):
    """
    Callback được gọi khi có chunk audio mới từ AudioRecorder
    
    Args:
        audio_data: Dữ liệu âm thanh dạng numpy array
        chunk_id: ID của chunk âm thanh
    """
    try:
        # Phân tích âm thanh để phát hiện tiếng khóc
        is_crying, features = detect_baby_crying(audio_data=audio_data)
        
        # Lọc các đoạn có tỉ lệ năng lượng trong dải tần số 250-750Hz cao
        target_freq_percent = features.get('target_frequency_energy_percent', 0)
        
        # Nếu phát hiện tiếng khóc và đủ năng lượng trong dải tần số mục tiêu
        if is_crying and target_freq_percent >= 40:
            logger.warning(f"⚠️ PHÁT HIỆN TIẾNG KHÓC CỦA EM BÉ ⚠️ (Chunk ID: {chunk_id})")
            logger.info(f"Năng lượng trong dải tần số 250-750Hz: {target_freq_percent:.2f}%")
            
            # Lưu audio chunk vào file
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"crying_{timestamp}.wav"
            filepath = os.path.join(AUDIO_DIR, filename)
            
            # Lưu file âm thanh
            if audio_recorder:
                audio_recorder.save_to_wav(audio_data, filename)
                
                # Đưa thông tin vào queue để xử lý trong thread riêng
                crying_data = {
                    'filepath': filepath,
                    'timestamp': timestamp,
                    'features': features
                }
                
                try:
                    crying_queue.put_nowait(crying_data)
                    crying_event.set()  # Đánh dấu có dữ liệu tiếng khóc mới
                except queue.Full:
                    logger.warning("Hàng đợi tiếng khóc đã đầy, bỏ qua đoạn âm thanh này")
                
    except Exception as e:
        logger.exception(f"Lỗi khi xử lý đoạn âm thanh {chunk_id}: {e}")

def crying_notification_thread():
    """
    Thread xử lý và gửi thông báo khi phát hiện tiếng khóc
    """
    last_notification_time = 0
    min_notification_interval = 5  # Thời gian tối thiểu giữa các thông báo (giây)
    
    while running:
        # Đợi cho đến khi có tiếng khóc mới hoặc timeout
        crying_event.wait(timeout=1.0)
        
        if crying_event.is_set():
            try:
                # Lấy dữ liệu từ queue
                crying_data = crying_queue.get_nowait()
                filepath = crying_data['filepath']
                timestamp = crying_data['timestamp']
                features = crying_data['features']
                
                # Kiểm tra thời gian từ thông báo cuối cùng
                current_time = time.time()
                if current_time - last_notification_time >= min_notification_interval:
                    # Gửi thông báo và cập nhật âm thanh
                    logger.info(f"Gửi thông báo tiếng khóc từ {filepath}")
                    
                    # Kiểm tra file có tồn tại
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        # Cập nhật vào server
                        update_status = update_latest_audio(filepath, is_crying=True)
                        if update_status:
                            logger.info(f"Đã cập nhật âm thanh có tiếng khóc: {os.path.basename(filepath)}")
                            
                            # Lưu file vào archive sau khi cập nhật
                            archive_path = os.path.join(ARCHIVE_DIR, os.path.basename(filepath))
                            os.makedirs(ARCHIVE_DIR, exist_ok=True)
                            
                            # Copy thay vì di chuyển file
                            try:
                                import shutil
                                shutil.copy2(filepath, archive_path)
                                logger.info(f"Đã sao lưu âm thanh: {os.path.basename(archive_path)}")
                            except Exception as e:
                                logger.error(f"Lỗi khi sao lưu file âm thanh: {e}")
                        else:
                            logger.error(f"Lỗi khi cập nhật âm thanh: {os.path.basename(filepath)}")
                    
                    # Cập nhật thời gian thông báo cuối cùng
                    last_notification_time = current_time
                    
                # Đánh dấu đã xử lý xong item này
                crying_queue.task_done()
                
                # Kiểm tra nếu queue rỗng thì reset event
                if crying_queue.empty():
                    crying_event.clear()
                    
            except queue.Empty:
                # Nếu queue rỗng, reset event
                crying_event.clear()
            except Exception as e:
                logger.exception(f"Lỗi khi xử lý thông báo tiếng khóc: {e}")
                crying_event.clear()

def signal_handler(sig, frame):
    """Xử lý khi nhận tín hiệu thoát"""
    global running
    logger.info("\nĐang dừng các luồng...")
    running = False

def start_monitoring():
    """Khởi động hệ thống giám sát"""
    global running, audio_recorder
    running = True
    
    # Tạo các thư mục cần thiết
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    
    # Khởi tạo audio recorder với sliding window
    audio_recorder = AudioRecorder(
        window_size=3,           # Cửa sổ 3 giây
        slide_size=1,            # Bước nhảy 1 giây
        save_audio=False,        # Không lưu mọi đoạn âm thanh, chỉ lưu khi phát hiện tiếng khóc
        audio_dir=AUDIO_DIR,     # Thư mục lưu âm thanh
        callback=process_audio_chunk  # Callback để xử lý mỗi đoạn âm thanh
    )
    
    # Khởi chạy các luồng
    photo_thread = threading.Thread(target=capture_photo_thread, name="PhotoThread")
    notification_thread = threading.Thread(target=crying_notification_thread, name="NotificationThread")
    
    # Khởi động HTTP server trong thread riêng
    http_thread = start_http_server_in_thread()
    
    # Khởi động WebSocket server trong thread riêng
    websocket_thread = start_websocket_server_in_thread()

    # Đặt các luồng là daemon để tự động kết thúc khi chương trình chính kết thúc
    photo_thread.daemon = True
    notification_thread.daemon = True
    # HTTP và WebSocket threads đã được đặt là daemon trong hàm của chúng

    # Khởi động các luồng
    photo_thread.start()
    notification_thread.start()

    logger.info(f"Đã khởi động hệ thống giám sát em bé - Thiết bị: {DEVICE_NAME}")
    logger.info(f"HTTP API và WebSocket server đã sẵn sàng")
    
    # Bắt đầu ghi âm với sliding window
    if audio_recorder:
        success = audio_recorder.start_recording()
        if success:
            logger.info("Đã bắt đầu ghi âm với chế độ sliding window")
        else:
            logger.error("Không thể khởi động ghi âm, kiểm tra PyAudio")
    
    # Đăng ký handler để bắt tín hiệu thoát
    signal.signal(signal.SIGINT, signal_handler)

    # Giữ chương trình chạy
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
        logger.info("Đang dừng chương trình...")
    
    # Dừng ghi âm
    if audio_recorder:
        audio_recorder.stop_recording()
        audio_recorder.close()
    
    # Đợi các luồng hoàn thành (có timeout)
    photo_thread.join(timeout=2)
    notification_thread.join(timeout=2)
    
    logger.info("Hệ thống giám sát đã dừng")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Hệ thống giám sát em bé trên Raspberry Pi')
    parser.add_argument('--mode', choices=['monitor', 'http', 'websocket'], default='monitor',
                      help='Chế độ hoạt động: monitor (mặc định), http, hoặc websocket')
    
    args = parser.parse_args()
    
    # Chọn chế độ chạy
    if args.mode == 'monitor':
        logger.info("Khởi động ở chế độ giám sát đầy đủ...")
        start_monitoring()
    elif args.mode == 'http':
        logger.info("Khởi động ở chế độ HTTP server...")
        from http_server import run_server
        run_server()
    elif args.mode == 'websocket':
        logger.info("Khởi động ở chế độ WebSocket server...")
        from websocket_server import run_websocket_server
        run_websocket_server()
    else:
        logger.error(f"Chế độ không hợp lệ: {args.mode}")