#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import time
import json
import requests
import argparse
from ..services.firebase_device_manager import authenticate_firebase, get_device_uuid, update_streaming_status

# Đường dẫn mặc định đến file nhị phân ngrok (thêm các vị trí phổ biến)
DEFAULT_NGROK_PATH = "/usr/local/bin/ngrok"
ALTERNATIVE_NGROK_PATHS = [
    "/usr/bin/ngrok",
    "/usr/local/bin/ngrok",
    "/home/pi/ngrok",
    os.path.join(os.path.expanduser("~"), "ngrok")
]
CONFIG_FILE = "ngrok_config.json"

def find_ngrok_binary():
    """
    Tìm file nhị phân ngrok trên hệ thống
    
    Returns:
        str: Đường dẫn đến ngrok nếu tìm thấy, None nếu không tìm thấy
    """
    # Kiểm tra theo thứ tự ưu tiên
    for path in ALTERNATIVE_NGROK_PATHS:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
            
    # Kiểm tra trong PATH
    try:
        result = subprocess.run(["which", "ngrok"], 
                             capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
        
    return None

def check_ngrok_installed(ngrok_path):
    """
    Kiểm tra xem ngrok đã được cài đặt hay chưa
    
    Args:
        ngrok_path (str): Đường dẫn đến file nhị phân ngrok
    
    Returns:
        bool: True nếu đã cài đặt, False nếu chưa
    """
    return os.path.exists(ngrok_path) and os.access(ngrok_path, os.X_OK)

def configure_ngrok(token=None, ngrok_path=DEFAULT_NGROK_PATH):
    """
    Cấu hình ngrok với token được cung cấp
    
    Args:
        token (str): Token ngrok (lấy từ tài khoản ngrok)
        ngrok_path (str): Đường dẫn đến file nhị phân ngrok
    
    Returns:
        bool: True nếu cấu hình thành công, False nếu không
    """
    if not check_ngrok_installed(ngrok_path):
        print(f"Không tìm thấy ngrok tại {ngrok_path}. Vui lòng cài đặt ngrok trước.")
        return False
    
    # Nếu không có token nhưng có file cấu hình, đọc từ file
    if not token and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                token = config.get('authtoken')
        except Exception as e:
            print(f"Lỗi khi đọc file cấu hình: {e}")
    
    # Nếu vẫn không có token, yêu cầu người dùng nhập
    if not token:
        token = input("Nhập ngrok authtoken (lấy từ https://dashboard.ngrok.com/get-started/your-authtoken): ")
    
    if not token:
        print("Không có token được cung cấp. Không thể cấu hình ngrok.")
        return False
    
    # Lưu token vào file cấu hình
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'authtoken': token}, f)
    except Exception as e:
        print(f"Lỗi khi lưu token: {e}")
    
    # Cấu hình ngrok với token
    try:
        print(f"Đang cấu hình ngrok với authtoken...")
        result = subprocess.run([ngrok_path, "config", "add-authtoken", token], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Cấu hình ngrok thành công!")
            return True
        else:
            print(f"Lỗi khi cấu hình ngrok: {result.stderr}")
            return False
    except Exception as e:
        print(f"Lỗi khi cấu hình ngrok: {e}")
        return False

def check_existing_ngrok_config(ngrok_path):
    """
    Kiểm tra xem ngrok đã được cấu hình trong hệ thống chưa
    
    Args:
        ngrok_path (str): Đường dẫn đến file nhị phân ngrok
        
    Returns:
        bool: True nếu ngrok đã được cấu hình, False nếu chưa
    """
    try:
        # Thử kiểm tra cấu hình hiện tại của ngrok
        result = subprocess.run([ngrok_path, "config", "list"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            # Kiểm tra xem có authtoken không
            if "authtoken" in result.stdout and "null" not in result.stdout:
                print("Phát hiện cấu hình ngrok có sẵn với authtoken.")
                return True
    except Exception as e:
        print(f"Lỗi khi kiểm tra cấu hình ngrok: {str(e)}")
    
    # Kiểm tra file cấu hình mặc định của ngrok
    home_dir = os.path.expanduser("~")
    ngrok_config_paths = [
        os.path.join(home_dir, ".ngrok2", "ngrok.yml"),  # Đường dẫn cũ
        os.path.join(home_dir, ".config", "ngrok", "ngrok.yml"),  # Đường dẫn mới
    ]
    
    for config_path in ngrok_config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    content = f.read()
                    if "authtoken" in content:
                        print(f"Phát hiện file cấu hình ngrok có sẵn tại {config_path}")
                        return True
            except Exception:
                pass
    
    return False

def is_ngrok_running():
    """
    Kiểm tra xem ngrok đã đang chạy chưa
    
    Returns:
        bool: True nếu ngrok đang chạy, False nếu không
    """
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        if response.status_code == 200:
            return True
        return False
    except:
        return False

def get_ngrok_url(retry=5, delay=1):
    """
    Lấy URL public của ngrok từ API cục bộ, thử lại nhiều lần nếu chưa có tunnel
    
    Args:
        retry (int): Số lần thử lại
        delay (int): Thời gian chờ giữa các lần thử (giây)
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    for attempt in range(retry):
        try:
            print(f"Đang truy cập API ngrok để lấy URL công khai... (lần {attempt+1})")
            response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
            print(f"Mã trạng thái API: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"Dữ liệu tunnels từ API: {data}")
                if 'tunnels' in data and len(data['tunnels']) > 0:
                    # Ưu tiên URL HTTPS
                    for tunnel in data.get('tunnels', []):
                        if tunnel.get('proto') == 'https':
                            url = tunnel.get('public_url')
                            print(f"Tìm thấy URL HTTPS: {url}")
                            return url
                    # Nếu không có HTTPS, lấy URL đầu tiên
                    url = data['tunnels'][0].get('public_url')
                    print(f"Không tìm thấy URL HTTPS, sử dụng URL đầu tiên: {url}")
                    return url
                else:
                    print("Không tìm thấy tunnels nào trong dữ liệu API")
            else:
                print(f"Không thể truy cập API ngrok. Mã trạng thái: {response.status_code}")
        except Exception as e:
            print(f"Lỗi khi lấy URL ngrok: {e}")
        if attempt < retry - 1:
            time.sleep(delay)
    # Thử phương pháp thay thế bằng cách chạy lệnh ngrok
    print("Thử phương pháp thay thế để lấy URL...")
    try:
        import re
        result = subprocess.run(["ps", "-ef", "|", "grep", "ngrok"], 
                              shell=True, capture_output=True, text=True)
        output = result.stdout
        print(f"Kết quả kiểm tra tiến trình ngrok: {output}")
        status_cmd = subprocess.run(["ngrok", "status", "--api=http://localhost:4040"], 
                                  capture_output=True, text=True)
        print(f"Kết quả lệnh ngrok status: {status_cmd.stdout}")
        urls = re.findall(r'(https?://[a-zA-Z0-9\-]+\.ngrok\.(io|free\.app))', status_cmd.stdout)
        if urls:
            print(f"Tìm thấy URL trong kết quả status: {urls[0][0]}")
            return urls[0][0]
    except Exception as e:
        print(f"Không thể sử dụng phương pháp thay thế: {e}")
    return None

def start_ngrok(port=80, ngrok_path=DEFAULT_NGROK_PATH):
    """
    Khởi động ngrok và tunneling đến port được chỉ định
    
    Args:
        port (int): Port cần tunneling
        ngrok_path (str): Đường dẫn đến file nhị phân ngrok
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    # Nếu ngrok đã chạy, lấy URL và trả về
    if is_ngrok_running():
        print("ngrok đã đang chạy.")
        url = get_ngrok_url()
        print(f"URL ngrok hiện tại: {url}")
        return url
    
    # Nếu chưa chạy, khởi động ngrok
    try:
        print(f"Khởi động ngrok để tunneling port {port}...")
        
        # Chạy ngrok trong tiến trình nền
        cmd = [ngrok_path, "http", str(port)]
        ngrok_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Đợi để ngrok khởi động
        for i in range(10):  # Đợi tối đa 10 giây
            time.sleep(1)
            if is_ngrok_running():
                url = get_ngrok_url()
                print(f"ngrok đã khởi động thành công. URL: {url}")
                return url
        
        print("Không thể khởi động ngrok sau 10 giây.")
        return None
    except Exception as e:
        print(f"Lỗi khi khởi động ngrok: {e}")
        return None

def main():
    """
    Hàm chính để thiết lập và quản lý ngrok
    """
    parser = argparse.ArgumentParser(description='Thiết lập và quản lý ngrok')
    parser.add_argument('--token', help='Authtoken ngrok')
    parser.add_argument('--config', action='store_true', help='Cấu hình ngrok với token')
    parser.add_argument('--start', action='store_true', help='Khởi động ngrok')
    parser.add_argument('--port', type=int, default=80, help='Port cần tunneling')
    parser.add_argument('--ngrok-path', default=DEFAULT_NGROK_PATH, help='Đường dẫn đến file nhị phân ngrok')
    
    args = parser.parse_args()
    
    # Tìm ngrok binary nếu đường dẫn mặc định không tồn tại
    if not os.path.exists(args.ngrok_path):
        detected_path = find_ngrok_binary()
        if detected_path:
            print(f"Đã tìm thấy ngrok tại: {detected_path}")
            args.ngrok_path = detected_path
        else:
            print(f"Không thể tìm thấy ngrok tại {args.ngrok_path} hoặc các vị trí thông thường khác.")
            print("Vui lòng cài đặt ngrok hoặc cung cấp đường dẫn chính xác với --ngrok-path")
            return
    
    # Xử lý các tùy chọn
    if args.config:
        configure_ngrok(args.token, args.ngrok_path)
    
    if args.start:
        url = start_ngrok(args.port, args.ngrok_path)
        if not url:
            print("Không thể khởi động ngrok.")
    
    # Nếu không có tùy chọn nào được chỉ định, tự động khởi động ngrok
    if not (args.config or args.start):
        print("Không có tùy chọn được chỉ định. Tự động khởi động ngrok với cấu hình mặc định...")
        
        # Kiểm tra cấu hình ngrok trong file cục bộ và hệ thống
        token_exists = False
        
        # Kiểm tra file cấu hình cục bộ
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    token_exists = 'authtoken' in config and config['authtoken']
            except Exception as e:
                print(f"Lỗi khi đọc file cấu hình cục bộ: {e}")
        
        # Nếu không có trong file cục bộ, kiểm tra cấu hình hệ thống
        if not token_exists:
            token_exists = check_existing_ngrok_config(args.ngrok_path)
        
        # Nếu chưa có token ở cả hai nơi, cấu hình mới
        if not token_exists:
            print("Chưa có authtoken ngrok. Cần cấu hình trước khi khởi động.")
            if args.token:
                configure_ngrok(args.token, args.ngrok_path)
            else:
                try:
                    configure_ngrok(None, args.ngrok_path)
                except KeyboardInterrupt:
                    print("\nĐã hủy cấu hình ngrok. Thoát chương trình.")
                    return
        
        # Khởi động ngrok
        url = start_ngrok(args.port, args.ngrok_path)
        if url:
            print(f"Ngrok đã khởi động thành công với URL: {url}")
        else:
            print("Không thể khởi động ngrok tự động. Hãy thử lại với --start hoặc kiểm tra lỗi.")

if __name__ == "__main__":
    main()
