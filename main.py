# File: main.py
# Main file for running the Baby Monitoring Raspberry Pi client

import os
import time
import signal
import sys
import argparse
import traceback

# Thêm log file để theo dõi quá trình khởi động
print("=== STARTING UP - INITIAL DIAGNOSTICS ===")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print("Checking for required directories...")

# Check and handle NumPy/SciPy errors
try:
    import numpy as np
    print("NumPy imported successfully")
    try:
        import scipy.signal
        print("SciPy imported successfully")
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
    from utils import logger, set_debug_mode
    print("✓ utils imported")
except ImportError as e:
    print(f"❌ Error importing utils: {e}")
    traceback.print_exc()
    sys.exit(1)

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
    from config import IMAGE_SERVER_URL, AUDIO_SERVER_URL
    print(f"✓ Server URLs loaded: ")
    print(f"  - Image server: {IMAGE_SERVER_URL}")
    print(f"  - Audio server: {AUDIO_SERVER_URL}")
except ImportError as e:
    print(f"❌ Error importing config: {e}")
    traceback.print_exc()

# Flag để kiểm soát kết thúc chương trình
running = True
# Flag để xác định chế độ debug
debug_mode = False

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
    data_group.add_argument('--no-vad', action='store_true', help='Tắt chức năng Voice Activity Detection (VAD)')
    
    # Nhóm tùy chọn hiển thị
    display_group = parser.add_argument_group('Tùy chọn hiển thị')
    display_group.add_argument('--simple-display', action='store_true', help='Sử dụng chế độ hiển thị đơn giản (tương thích tốt hơn)')
    display_group.add_argument('--debug', action='store_true', help='Hiển thị thông tin log và chi tiết lỗi')
    
    # Nhóm tùy chọn server
    server_group = parser.add_argument_group('Cấu hình kết nối server')
    server_group.add_argument('--image-server', help='Địa chỉ server hình ảnh (IP:port hoặc hostname:port)')
    server_group.add_argument('--audio-server', help='Địa chỉ server âm thanh (IP:port hoặc hostname:port)')
    
    return parser.parse_args()

def main():
    """Main function to start the program"""
    global debug_mode
    
    # Đăng ký handler cho tín hiệu dừng chương trình
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Xử lý tham số dòng lệnh
    args = parse_arguments()
    
    # Cấu hình chế độ hiển thị log - mặc định tắt, chỉ bật khi có --debug
    try:
        if args.debug:
            print("\n>> Đang chuyển sang chế độ debug (hiển thị log)")
            set_debug_mode(True)
            debug_mode = True
        else:
            set_debug_mode(False)
            debug_mode = False
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
        import re
        from urllib.parse import urlparse
        from config import CONNECTION_CONFIG, save_connection_config
        
        # Xử lý tham số VAD (Voice Activity Detection)
        import config
        if args.no_vad:
            print("\n>> Đang tắt tính năng Voice Activity Detection (VAD)")
            config.USE_VAD = False
        else:
            # Mặc định là bật
            config.USE_VAD = True
            print("\n>> Tính năng Voice Activity Detection (VAD) đang bật")
        
        # Function to parse different server address formats
        def parse_server_address(address):
            """
            Parse server address in various formats:
            - IP:port (e.g., 192.168.1.10:8080)
            - hostname:port (e.g., example.com:8080)
            - Full URL (e.g., http://example.com:8080, https://xxxx-xx-xx-xx.ngrok-free.app)
            
            Returns a tuple of (host, port, use_ngrok, use_ssl)
            """
            use_ngrok = False
            use_ssl = False
            
            # Check if it's a full URL with protocol
            if "://" in address:
                parsed_url = urlparse(address)
                protocol = parsed_url.scheme
                use_ssl = (protocol == 'https')
                
                # Check if it's an ngrok URL
                if 'ngrok' in parsed_url.netloc:
                    use_ngrok = True
                
                # Extract host and path
                host = parsed_url.netloc
                
                # Extract port if specified in URL
                if ':' in host:
                    host, port_str = host.split(':', 1)
                    # Handle case where port may include path
                    port_str = port_str.split('/', 1)[0]
                    port = int(port_str)
                else:
                    # Use default ports based on protocol
                    port = 443 if use_ssl else 80
                
                return host, port, use_ngrok, use_ssl
            
            # Handle IP:port or hostname:port format
            elif ':' in address:
                host, port_str = address.split(':', 1)
                port = int(port_str)
                
                # Check if it might be an ngrok hostname without protocol
                if 'ngrok' in host:
                    use_ngrok = True
                    use_ssl = True  # Ngrok usually uses HTTPS
                
                return host, port, use_ngrok, use_ssl
            
            # Just a hostname or IP without port
            else:
                host = address
                # Check if it might be an ngrok hostname without protocol
                if 'ngrok' in host:
                    use_ngrok = True
                    use_ssl = True
                    port = 443  # HTTPS default port
                else:
                    port = 80  # HTTP default port
                
                return host, port, use_ngrok, use_ssl
        
        # Xử lý các tham số server tùy chọn
        # Kiểm tra nếu người dùng đã nhập địa chỉ server hình ảnh
        if args.image_server:
            print(f"\n>> Đang cấu hình kết nối đến server hình ảnh: {args.image_server}")
            
            # Parse the provided address
            host, port, use_ngrok, use_ssl = parse_server_address(args.image_server)
            
            # Cập nhật cấu hình server hình ảnh
            CONNECTION_CONFIG["image_server"]["use_ngrok"] = use_ngrok
            CONNECTION_CONFIG["image_server"]["local_host"] = host
            CONNECTION_CONFIG["image_server"]["local_port"] = port
            CONNECTION_CONFIG["image_server"]["use_ssl"] = use_ssl
            
            # Nếu là URL ngrok, cập nhật ngrok_url
            if use_ngrok:
                CONNECTION_CONFIG["image_server"]["ngrok_url"] = host
                print(f"  - Đã phát hiện địa chỉ ngrok: {host}")
                print(f"  - Sử dụng HTTPS: {'Có' if use_ssl else 'Không'}")
            else:
                print(f"  - Host: {host}")
                print(f"  - Port: {port}")
        
        # Kiểm tra nếu người dùng đã nhập địa chỉ server âm thanh
        if args.audio_server:
            print(f"\n>> Đang cấu hình kết nối đến server âm thanh: {args.audio_server}")
            
            # Parse the provided address
            host, port, use_ngrok, use_ssl = parse_server_address(args.audio_server)
            
            # Cập nhật cấu hình server âm thanh
            CONNECTION_CONFIG["audio_server"]["use_ngrok"] = use_ngrok
            CONNECTION_CONFIG["audio_server"]["local_host"] = host
            CONNECTION_CONFIG["audio_server"]["local_port"] = port
            CONNECTION_CONFIG["audio_server"]["use_ssl"] = use_ssl
            
            # Nếu là URL ngrok, cập nhật ngrok_url
            if use_ngrok:
                CONNECTION_CONFIG["audio_server"]["ngrok_url"] = host
                print(f"  - Đã phát hiện địa chỉ ngrok: {host}")
                print(f"  - Sử dụng HTTPS: {'Có' if use_ssl else 'Không'}")
            else:
                print(f"  - Host: {host}")
                print(f"  - Port: {port}")
        
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
        if debug_mode:
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
    
    # Hiển thị thông tin về chế độ chạy
    if debug_mode:
        print("\n>> CHẾ ĐỘ DEBUG ĐANG BẬT - Chỉ hiển thị log, không hiển thị giao diện trạng thái")
    else:
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
    
    # THAY ĐỔI HOÀN TOÀN: Tách biệt rõ ràng giữa chế độ debug và chế độ hiển thị giao diện
    try:
        # TH1: Nếu là chế độ debug, không hiển thị giao diện, chỉ chờ tín hiệu kết thúc
        if debug_mode:
            # Chỉ hiển thị thông báo ban đầu rồi để cho log hiển thị
            logger.info("Running in debug mode - Only showing logs, no status interface")
            logger.info(f"Audio module: {'Running' if audio_client else 'Disabled'}")
            logger.info(f"Camera module: {'Running' if camera_client else 'Disabled'}")
            
            # Chỉ chờ tín hiệu kết thúc
            while running:
                time.sleep(1.0)
                
        # TH2: Nếu là chế độ hiển thị đơn giản, cập nhật định kỳ và xóa màn hình
        elif args.simple_display:
            print("\n>> Sử dụng chế độ hiển thị đơn giản")
            last_display_time = 0
            display_interval = 5  # Cập nhật mỗi 5 giây
            
            while running:
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    # Xóa màn hình cũ (Windows/Linux)
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                    # Lấy và hiển thị trạng thái mới
                    status_lines = get_status_display()
                    print("\n".join(status_lines))
                    print("\nPress Ctrl+C to exit")
                    
                    last_display_time = current_time
                
                # Nghỉ để giảm CPU
                time.sleep(0.5)
                
        # TH3: Mặc định - Sử dụng ANSI để hiển thị giao diện động
        else:
            print("\n>> Bắt đầu hiển thị giao diện trạng thái...")
            
            # Xóa màn hình và ẩn con trỏ
            print("\033[2J\033[H\033[?25l", end="", flush=True)
            
            previous_output = ""
            
            while running:
                try:
                    # Lấy trạng thái hiện tại
                    status_lines = get_status_display()
                    current_output = "\n".join(status_lines)
                    
                    # Chỉ cập nhật nếu có sự thay đổi
                    if current_output != previous_output:
                        # Di chuyển đến đầu màn hình
                        print("\033[H", end="", flush=True)
                        
                        # In trạng thái mới
                        print(current_output, flush=True)
                        
                        # Xóa đến cuối màn hình để loại bỏ nội dung cũ
                        print("\033[J", end="", flush=True)
                        
                        # Lưu đầu ra hiện tại
                        previous_output = current_output
                    
                    # Đợi trước khi cập nhật tiếp theo
                    time.sleep(update_interval)
                except Exception as e:
                    print(f"Lỗi hiển thị: {e}")
                    # Chuyển sang chế độ hiển thị đơn giản
                    print("\nChuyển sang chế độ hiển thị đơn giản...")
                    args.simple_display = True
                    break
                
    except KeyboardInterrupt:
        print("\nNhận tín hiệu Ctrl+C, đang dừng hệ thống...")
    except Exception as e:
        print(f"Lỗi hệ thống: {e}")
        if debug_mode:
            traceback.print_exc()
    finally:
        # Hiển thị lại con trỏ
        print("\033[?25h", end="", flush=True)
    
    # Dọn dẹp khi thoát
    print("\nĐang dừng hệ thống...")
    
    if audio_client:
        print(">> Stopping audio module...")
        audio_client.stop_recording()
        audio_client.close()
        
    if camera_client:
        print(">> Stopping image module...")
        camera_client.stop()
    
    # Hiển thị trạng thái cuối cùng (chỉ khi không ở chế độ debug)
    if not debug_mode:
        print("\nTrạng thái cuối cùng:")
        final_status = get_status_display()
        print("\n".join(final_status))
    
    print("\n✓ Hệ thống đã dừng an toàn")
    return 0

if __name__ == "__main__":
    main()