# File: main.py
# Main file for running the Baby Monitoring Raspberry Pi client

import os
import time
import signal
import sys
import argparse
import traceback

# Tắt hiển thị log ra console ngay từ đầu (mặc định chỉ hiển thị giao diện)
import logging
logging.getLogger('pi-client').handlers = []  # Xóa tất cả handlers mặc định

# Thêm log file để theo dõi quá trình khởi động
print("=== STARTING UP - INITIAL DIAGNOSTICS ===")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print("Checking for required directories...")

# ===== KHÔNG XÓA STDERR ĐỂ CÓ THỂ XEM LỖI =====
# Comment dòng code chuyển hướng stderr để có thể thấy thông báo lỗi
# os.environ['PYTHONUNBUFFERED'] = '1'
# devnull = os.open(os.devnull, os.O_WRONLY)
# old_stderr = os.dup(2)
# sys.stderr.flush()
# os.dup2(devnull, 2)
# os.close(devnull)

# Check and handle NumPy/SciPy errors
try:
    # Tạm thời bỏ qua việc khôi phục stderr vì chúng ta không chuyển hướng nó nữa
    # os.dup2(old_stderr, 2)
    import numpy as np
    print("NumPy imported successfully")
    try:
        import scipy.signal
        print("SciPy imported successfully")
        # Không chuyển hướng stderr nữa
        # devnull = os.open(os.devnull, os.O_WRONLY)
        # os.dup2(devnull, 2)
        # os.close(devnull)
    except ImportError:
        print("\n❌ Error: NumPy and SciPy versions are incompatible!")
        print("Please reinstall the libraries with compatible versions:")
        print("\nsudo pip uninstall -y numpy scipy")
        print("sudo apt-get update")
        print("sudo apt-get install -y python3-numpy python3-scipy")
        print("\nOr if you need specific versions via pip:")
        print("pip install numpy==1.16.6 scipy==1.2.3\n")
        sys.exit(1)
except ImportError:
    print("\n❌ Error: Cannot import NumPy!")
    print("Please install NumPy with:")
    print("\nsudo apt-get update")
    print("sudo apt-get install -y python3-numpy libatlas-base-dev\n")
    sys.exit(1)

# Import các module cần thiết
print("Importing modules...")
try:
    from audio_client import AudioRecorder
    print("✓ audio_client imported")
except ImportError as e:
    print(f"❌ Error importing audio_client: {e}")
    traceback.print_exc()

try:
    from camera_client import CameraClient
    print("✓ camera_client imported")
except ImportError as e:
    print(f"❌ Error importing camera_client: {e}")
    traceback.print_exc()

try:
    from utils import logger
    print("✓ utils imported")
except ImportError as e:
    print(f"❌ Error importing utils: {e}")
    traceback.print_exc()

try:
    from config import IMAGE_SERVER_URL, AUDIO_SERVER_URL
    print(f"✓ Server URLs loaded: ")
    print(f"  - Image server: {IMAGE_SERVER_URL}")
    print(f"  - Audio server: {AUDIO_SERVER_URL}")
except ImportError as e:
    print(f"❌ Error importing config: {e}")
    traceback.print_exc()

# Flag to control program exit
running = True

def signal_handler(sig, frame):
    """Handle system shutdown signals."""
    global running
    print("\nStopping system...")
    running = False

def parse_arguments():
    """Process command line arguments"""
    parser = argparse.ArgumentParser(description='Raspberry Pi client for baby monitoring system')
    
    # Nhóm tùy chọn truyền dữ liệu
    data_group = parser.add_argument_group('Tùy chọn truyền dữ liệu')
    data_group.add_argument('--camera-mode', action='store_true', help='Chỉ chạy chế độ truyền hình ảnh')
    data_group.add_argument('--audio-mode', action='store_true', help='Chỉ chạy chế độ truyền âm thanh')
    
    # Nhóm tùy chọn hiển thị
    display_group = parser.add_argument_group('Tùy chọn hiển thị')
    display_group.add_argument('--simple-display', action='store_true', help='Sử dụng chế độ hiển thị đơn giản (tương thích tốt hơn)')
    
    # Thêm tùy chọn cho chế độ hiển thị log
    log_group = parser.add_argument_group('Tùy chọn hiển thị log')
    log_display = log_group.add_mutually_exclusive_group()
    log_display.add_argument('--quiet', action='store_true', help='Chỉ hiển thị giao diện, không hiện log/lỗi')
    log_display.add_argument('--verbose', action='store_true', help='Hiển thị chi tiết log/lỗi')
    
    # Nhóm tùy chọn server
    server_group = parser.add_argument_group('Cấu hình kết nối server')
    server_group.add_argument('--image-server', help='Địa chỉ server hình ảnh (IP:port hoặc hostname:port)')
    server_group.add_argument('--audio-server', help='Địa chỉ server âm thanh (IP:port hoặc hostname:port)')
    
    return parser.parse_args()

def main():
    """Main function to start the program"""
    # Register signal handlers for program termination
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Process command line arguments
    args = parse_arguments()
    
    # Cấu hình chế độ hiển thị log - thực hiện trước để điều khiển log trong quá trình khởi động
    try:
        from utils import set_console_logging
        
        if args.quiet:
            print("\n>> Đang chuyển sang chế độ hiển thị giao diện (không hiện log)")
            set_console_logging(enabled=False)
        elif args.verbose:
            print("\n>> Đang chuyển sang chế độ hiển thị đầy đủ log")
            set_console_logging(enabled=True)
    except Exception as e:
        print(f"Lỗi khi cấu hình chế độ hiển thị log: {e}")
    
    # System start time
    start_time = time.time()
    
    # Print startup information
    print("\n" + "=" * 60)
    print("BABY MONITORING SYSTEM - Raspberry Pi Client")
    print("=" * 60)
    
    # Áp dụng cấu hình kết nối từ tham số dòng lệnh
    try:
        # Import các module cần thiết cho cấu hình kết nối
        import json
        from config import CONNECTION_CONFIG, save_connection_config
        
        # Xử lý các tham số server tùy chọn
        # Kiểm tra nếu người dùng đã nhập địa chỉ server hình ảnh
        if args.image_server:
            print(f"\n>> Đang cấu hình kết nối đến server hình ảnh: {args.image_server}")
            
            # Tách host và port từ chuỗi nhập vào (định dạng host:port)
            if ":" in args.image_server:
                host, port = args.image_server.split(":")
                port = int(port)
                
                # Cập nhật cấu hình server hình ảnh
                CONNECTION_CONFIG["image_server"]["use_ngrok"] = False
                CONNECTION_CONFIG["image_server"]["local_host"] = host
                CONNECTION_CONFIG["image_server"]["local_port"] = port
                
                print(f"  - Host: {host}")
                print(f"  - Port: {port}")
            else:
                # Nếu chỉ có host, sử dụng port mặc định 80
                CONNECTION_CONFIG["image_server"]["use_ngrok"] = False
                CONNECTION_CONFIG["image_server"]["local_host"] = args.image_server
                CONNECTION_CONFIG["image_server"]["local_port"] = 80
                
                print(f"  - Host: {args.image_server}")
                print(f"  - Port: 80 (mặc định)")
        
        # Kiểm tra nếu người dùng đã nhập địa chỉ server âm thanh
        if args.audio_server:
            print(f"\n>> Đang cấu hình kết nối đến server âm thanh: {args.audio_server}")
            
            # Tách host và port từ chuỗi nhập vào (định dạng host:port)
            if ":" in args.audio_server:
                host, port = args.audio_server.split(":")
                port = int(port)
                
                # Cập nhật cấu hình server âm thanh
                CONNECTION_CONFIG["audio_server"]["use_ngrok"] = False
                CONNECTION_CONFIG["audio_server"]["local_host"] = host
                CONNECTION_CONFIG["audio_server"]["local_port"] = port
                
                print(f"  - Host: {host}")
                print(f"  - Port: {port}")
            else:
                # Nếu chỉ có host, sử dụng port mặc định 80
                CONNECTION_CONFIG["audio_server"]["use_ngrok"] = False
                CONNECTION_CONFIG["audio_server"]["local_host"] = args.audio_server
                CONNECTION_CONFIG["audio_server"]["local_port"] = 80
                
                print(f"  - Host: {args.audio_server}")
                print(f"  - Port: 80 (mặc định)")
        
        # Lưu cấu hình mới vào file
        print("\n>> Đang lưu cấu hình kết nối...")
        save_connection_config(CONNECTION_CONFIG)
        
        # Tải lại các URL từ cấu hình mới
        from config import get_server_url, get_ws_url
        
        # Cập nhật lại các biến toàn cục trong module config
        import config
        config.IMAGE_SERVER_URL = get_server_url("image")
        config.AUDIO_SERVER_URL = get_server_url("audio")
        config.IMAGE_API_ENDPOINT = f"{config.IMAGE_SERVER_URL}/api/images"
        config.AUDIO_API_ENDPOINT = f"{config.AUDIO_SERVER_URL}/api/audio"
        config.IMAGE_WS_ENDPOINT = get_ws_url("image")
        config.AUDIO_WS_ENDPOINT = get_ws_url("audio")
        
        # Phân tích URL để lấy host và port
        # IMAGE_SERVER_URL dạng http(s)://host:port
        if "://" in config.IMAGE_SERVER_URL:
            image_url_parts = config.IMAGE_SERVER_URL.split("://")[1].split(":")
            config.IMAGE_SERVER_HOST = image_url_parts[0]
            if len(image_url_parts) > 1:
                config.IMAGE_SERVER_PORT = int(image_url_parts[1].split("/")[0])
        
        # AUDIO_SERVER_URL dạng http(s)://host:port hoặc http(s)://host (không có port)
        if "://" in config.AUDIO_SERVER_URL:
            audio_url_parts = config.AUDIO_SERVER_URL.split("://")[1].split(":")
            config.AUDIO_SERVER_HOST = audio_url_parts[0]
            if len(audio_url_parts) > 1:
                config.AUDIO_SERVER_PORT = int(audio_url_parts[1].split("/")[0])
            else:
                config.AUDIO_SERVER_PORT = 443 if "https://" in config.AUDIO_SERVER_URL else 80
        
        # Hiển thị thông tin kết nối đã cập nhật
        print("\n>> Cấu hình kết nối hiện tại:")
        print(f"• Server hình ảnh: {config.IMAGE_SERVER_HOST}:{config.IMAGE_SERVER_PORT}")
        print(f"• Server âm thanh: {config.AUDIO_SERVER_HOST}:{config.AUDIO_SERVER_PORT}")
        
    except Exception as e:
        print(f"\n>> Lỗi khi cập nhật cấu hình kết nối: {e}")
        if args.debug:
            print("Chi tiết lỗi:")
            traceback.print_exc()
    
    # Initialize clients
    audio_client = None
    camera_client = None
    
    # Cập nhật cách xác định mode chạy (chỉ audio, chỉ camera hoặc cả hai)
    run_audio_mode = not args.camera_mode  # Chạy audio nếu không phải chỉ chạy camera
    run_camera_mode = not args.audio_mode  # Chạy camera nếu không phải chỉ chạy audio
    
    # Thông báo về chế độ đang chạy
    print("\n>> Chế độ hoạt động:")
    if run_audio_mode and run_camera_mode:
        print("  - Chạy cả hai chế độ: Truyền âm thanh và hình ảnh")
    elif run_audio_mode:
        print("  - Chỉ chạy chế độ truyền âm thanh")
    elif run_camera_mode:
        print("  - Chỉ chạy chế độ truyền hình ảnh")
    else:
        print("  - Lưu ý: Cả hai chế độ đều bị tắt, sẽ bật cả hai")
        run_audio_mode = True
        run_camera_mode = True
    
    # Start AudioRecorder if enabled
    if run_audio_mode:
        print("\n>> Starting audio processing module...")
        try:
            audio_client = AudioRecorder()
            audio_client.start_recording()
            print("✓ Audio module started successfully")
        except Exception as e:
            print(f"✗ Cannot start audio module: {e}")
            print("Detailed error:")
            traceback.print_exc()
            audio_client = None
    
    # Start CameraClient if enabled
    if run_camera_mode:
        print("\n>> Starting image processing module...")
        try:
            # Lấy khoảng thời gian chụp ảnh từ cấu hình thay vì tham số dòng lệnh
            from config import PHOTO_INTERVAL
            camera_client = CameraClient(interval=PHOTO_INTERVAL)
            if not camera_client.start():
                print("✗ Camera client start() returned False")
                camera_client = None
            else:
                print("✓ Image module started successfully")
        except Exception as e:
            print(f"✗ Cannot start image module: {e}")
            print("Detailed error:")
            traceback.print_exc()
            camera_client = None
    
    if not audio_client and not camera_client:
        print("\n❌ Error: Cannot start any module. Program will exit.")
        return
    
    # Print initial information about running modules
    print("\n" + "-" * 60)
    print("System Information:")
    print(f"• Audio mode: {'Running' if audio_client else 'Disabled'}")
    print(f"• Camera mode: {'Running' if camera_client else 'Disabled'}")
    print(f"• Connection method: WebSocket")
    
    # Display server information
    from config import AUDIO_SERVER_HOST, AUDIO_SERVER_PORT, IMAGE_SERVER_HOST, IMAGE_SERVER_PORT
    print(f"• Audio server: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
    print(f"• Image server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
    
    if camera_client:
        # Lấy thông tin khoảng thời gian chụp ảnh từ config
        from config import PHOTO_INTERVAL
        print(f"• Capture photos: every {PHOTO_INTERVAL} seconds")
    
    print("-" * 60)
    print("\nSystem running. Press Ctrl+C to stop.")
    print("Status display will start in 2 seconds...")
    time.sleep(2)  # Give time to read initial info
    
    # Update interval
    update_interval = 1.0
    
    # Function to get status information with improved display format
    def get_status_display():
        runtime = time.time() - start_time
        hours, remainder = divmod(int(runtime), 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        current_time = time.strftime("%H:%M:%S", time.localtime())
        
        status_lines = []
        status_lines.append("=" * 60)
        status_lines.append(f"BABY MONITORING SYSTEM - Runtime: {runtime_str}")
        status_lines.append("=" * 60)
        
        # Connection status lines - one per server
        audio_ws_status = "Connected" if audio_client and audio_client.ws_connected else "Connecting..."
        status_lines.append(f"• Audio Server: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT} | Status: {audio_ws_status}")
        
        image_ws_status = "Connected" if camera_client and camera_client.ws_connected else "Connecting..."
        status_lines.append(f"• Image Server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT} | Status: {image_ws_status}")
        
        # Audio information
        if audio_client:
            # Improve status display
            audio_status = "Recording" if audio_client.is_recording else "Paused"
            status_lines.append(f"• Audio: Every 1s")
            status_lines.append(f"  Status: {audio_status}")
            status_lines.append(f"  File: audio_chunk_{audio_client.save_counter}")
            status_lines.append(f"  - Process time: ~{audio_client.window_size*0.8:.1f}s | Send time: ~{audio_client.window_size/10:.1f}s")
            
            # Queue information - only show successfully processed items, not sent
            queue_size = audio_client.chunk_queue.qsize() if hasattr(audio_client.chunk_queue, 'qsize') else 0
            processed = audio_client.save_counter
            sent = 0  # Resetting sent count because we're not actually connected
            if audio_client.ws_connected:
                sent = processed  # Only consider items sent if we're connected
            status_lines.append(f"  - Processed: {processed} | Sent: {sent} | Queue: {queue_size}")
            status_lines.append(f"  - Window: {audio_client.window_size}s | Slide: {audio_client.slide_size}s | {audio_client.sample_rate} Hz, {audio_client.channels}ch")
        
        # Camera information
        if camera_client:
            capture_time = f"{camera_client.capture_duration:.1f}s"
            sending_time = f"{camera_client.sending_duration:.1f}s"
            
            # Fix trạng thái hiển thị - Cách hoàn toàn mới để ngăn lỗi ghép trạng thái
            # Thay vì dựa vào camera_client.processing_status có thể bị lỗi
            # chúng ta sẽ xác định trạng thái theo thời gian
            current_time = time.time()
            time_since_capture = current_time - camera_client.last_capture_time
            time_since_sent = current_time - camera_client.last_sent_time if camera_client.last_sent_time > 0 else 999
            
            # Xác định trạng thái dựa trên thời gian
            camera_status = "Waiting"
            if time_since_capture < 1.0:
                # Nếu vừa chụp ảnh trong vòng 1 giây
                camera_status = "Capturing image..."
            elif time_since_sent < 1.0:
                # Nếu vừa gửi ảnh trong vòng 1 giây
                camera_status = "Sending image..."
            elif camera_client.sent_fail_count > 0:
                # Nếu có ảnh bị lỗi khi gửi
                camera_status = "Send error"
            elif camera_client.sent_success_count > 0:
                # Nếu gửi thành công
                camera_status = "Sent successfully"
            
            # Sử dụng thời gian chụp từ camera_client.interval
            status_lines.append(f"• Images: Every {camera_client.interval}s")
            status_lines.append(f"  - Status: {camera_status}")
            status_lines.append(f"  File: {camera_client.current_photo_file}")
            status_lines.append(f"  Resolution: 640x480px")
            status_lines.append(f"  - Capture: {capture_time} | Send: {sending_time}")
            
            # Only count as sent if we're actually connected
            sent_count = 0
            if camera_client.ws_connected:
                sent_count = camera_client.sent_success_count
            
            # Hiển thị kích thước hàng đợi đúng, sử dụng queue_size_counter thay vì sent_fail_count
            queue_size = camera_client.queue_size_counter if hasattr(camera_client, 'queue_size_counter') else 0
            status_lines.append(f"  - Captured: {camera_client.total_photos_taken} | Sent: {sent_count} | Queue: {queue_size}")
        
        return status_lines
    
    # Try to use alternative display method that works better in all terminals
    try:
        # Kiểm tra xem có sử dụng chế độ hiển thị đơn giản không
        if args.simple_display:
            print("\n>> Using simple display mode for compatibility")
            # Main loop - Simple display
            last_display_time = 0
            display_interval = 5  # Update every 5 seconds
            
            while running:
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    # Get current status
                    status_lines = get_status_display()
                    
                    # Print new status with a separator
                    print("\n" + "-" * 60)
                    print("\n".join(status_lines))
                    print("-" * 60)
                    
                    last_display_time = current_time
                
                # Wait a bit to avoid high CPU usage
                time.sleep(0.5)
        else:
            # First clear any existing output and disable cursor
            print("\033[2J\033[H\033[?25l", end="", flush=True)  # Clear screen, home cursor, hide cursor
            
            previous_output = ""
            
            # Main display loop
            while running:
                try:
                    # Get current status
                    status_lines = get_status_display()
                    current_output = "\n".join(status_lines)
                    
                    # Only update if something changed
                    if current_output != previous_output:
                        # Move cursor to home position
                        print("\033[H", end="", flush=True)
                        
                        # Print new status
                        print(current_output, end="", flush=True)
                        
                        # Clear to end of screen to remove any previous content
                        print("\033[J", end="", flush=True)
                        
                        # Remember output
                        previous_output = current_output
                    
                    # Wait for next update
                    time.sleep(update_interval)
                except Exception as e:
                    # If we encounter an error with this display method, fall back
                    logger.error(f"Display error: {e}")
                    print(f"\nDisplay error: {e}")
                    print("Falling back to simple display mode...")
                    
                    # Switch to simple display mode
                    args.simple_display = True
                    break
                    
    except KeyboardInterrupt:
        print("\nCtrl+C pressed, stopping system")
        logger.info("Stop signal received from user")
    except Exception as e:
        print(f"\nError in main loop: {e}")
        traceback.print_exc()
    finally:
        # Show cursor again
        print("\033[?25h", end="", flush=True)
    
    # Cleanup on exit
    print("\n\nStopping system...")
    
    if audio_client:
        print(">> Stopping audio module...")
        audio_client.stop_recording()
        audio_client.close()
        
    if camera_client:
        print(">> Stopping image module...")
        camera_client.stop()
        
    # Show final status
    print("\nFinal system status:")
    final_status = get_status_display()
    print("\n".join(final_status))
    print("\n✓ System stopped safely")
    
    # Ensure we exit properly
    return 0

if __name__ == "__main__":
    main()