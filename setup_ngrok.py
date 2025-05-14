#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import time
import json
import requests
import argparse
from firebase_device_manager import authenticate_firebase, get_device_uuid, update_streaming_status

# Đường dẫn mặc định đến file nhị phân ngrok
DEFAULT_NGROK_PATH = "/usr/local/bin/ngrok"
CONFIG_FILE = "ngrok_config.json"

def check_ngrok_installed(ngrok_path):
    """
    Kiểm tra xem ngrok đã được cài đặt hay chưa
    
    Args:
        ngrok_path (str): Đường dẫn đến file nhị phân ngrok
    
    Returns:
        bool: True nếu đã cài đặt, False nếu chưa
    """
    return os.path.exists(ngrok_path)

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

def get_ngrok_url():
    """
    Lấy URL public của ngrok từ API cục bộ
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=3)
        if response.status_code == 200:
            data = response.json()
            # Ưu tiên URL HTTPS
            for tunnel in data.get('tunnels', []):
                if tunnel.get('proto') == 'https':
                    return tunnel.get('public_url')
            
            # Nếu không có HTTPS, lấy URL đầu tiên
            if data.get('tunnels'):
                return data['tunnels'][0].get('public_url')
        
        print(f"Không tìm thấy URL ngrok.")
        return None
    except Exception as e:
        print(f"Lỗi khi lấy URL ngrok: {e}")
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
    
    # Xử lý các tùy chọn
    if args.config:
        configure_ngrok(args.token, args.ngrok_path)
    
    if args.start:
        url = start_ngrok(args.port, args.ngrok_path)
        if not url:
            print("Không thể khởi động ngrok.")
    
    # Nếu không có tùy chọn nào được chỉ định, hiển thị help
    if not (args.config or args.start or args.update_uri):
        parser.print_help()

if __name__ == "__main__":
    main()