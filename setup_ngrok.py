#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
import sys
import signal
import argparse

# Đường dẫn mặc định đến ngrok binary
NGROK_DEFAULT_PATH = "/usr/local/bin/ngrok"

def is_ngrok_running():
    """
    Kiểm tra xem ngrok đã đang chạy chưa bằng cách thử kết nối đến API local
    
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
    Lấy URL public của ngrok từ API cục bộ.
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # Tìm tunnel HTTPS hoặc HTTP
            for tunnel in data.get('tunnels', []):
                if tunnel.get('proto') == 'https':
                    return tunnel.get('public_url')
                elif tunnel.get('proto') == 'http':
                    return tunnel.get('public_url')
            
            # Nếu không tìm thấy tunnel HTTPS/HTTP cụ thể, lấy tunnel đầu tiên
            if data.get('tunnels'):
                return data['tunnels'][0].get('public_url')
        
        print(f"Không tìm thấy URL ngrok. Mã trạng thái: {response.status_code}")
        return None
    except Exception as e:
        print(f"Lỗi khi lấy URL ngrok: {str(e)}")
        return None

def start_ngrok(port=80, ngrok_path=NGROK_DEFAULT_PATH, region=None, domain=None, authtoken=None):
    """
    Khởi động ngrok nếu chưa đang chạy
    
    Args:
        port: Port để tạo tunnel (mặc định 80 cho web server)
        ngrok_path: Đường dẫn đến ngrok binary
        region: Khu vực server ngrok (vd: us, eu, au, ap, sa, jp, in)
        domain: Tên miền tùy chỉnh nếu bạn đang sử dụng ngrok Pro/Business
        authtoken: Token xác thực ngrok, nếu chưa được cấu hình
    
    Returns:
        str: URL ngrok public hoặc None nếu có lỗi
    """
    if is_ngrok_running():
        print("ngrok đã đang chạy!")
        url = get_ngrok_url()
        print(f"URL ngrok hiện tại: {url}")
        return url
        
    print("Bắt đầu khởi động ngrok...")
    
    # Chuẩn bị lệnh ngrok
    cmd = [ngrok_path, "http", str(port)]
    
    # Thêm các tùy chọn nếu được cung cấp
    if region:
        cmd.extend(["--region", region])
    
    if domain:
        cmd.extend(["--domain", domain])
    
    if authtoken:
        # Cấu hình authtoken trước
        auth_cmd = [ngrok_path, "authtoken", authtoken]
        try:
            subprocess.run(auth_cmd, check=True)
            print(f"Đã thiết lập authtoken ngrok thành công")
        except subprocess.CalledProcessError as e:
            print(f"Lỗi khi thiết lập authtoken: {str(e)}")
            return None
    
    # Khởi động ngrok trong tiến trình con
    try:
        # Chạy ngrok dưới dạng tiến trình nền
        ngrok_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Đợi để ngrok khởi động
        for _ in range(10):  # Thử trong 10 giây
            time.sleep(1)
            if is_ngrok_running():
                break
        
        if is_ngrok_running():
            url = get_ngrok_url()
            if url:
                print(f"ngrok đã khởi động thành công. URL: {url}")
                return url
            else:
                print("ngrok đã khởi động nhưng không thể lấy được URL")
                return None
        else:
            print("Không thể khởi động ngrok. Kiểm tra lại cài đặt ngrok.")
            # Đọc output để xem lỗi
            stdout, stderr = ngrok_process.communicate(timeout=2)
            if stdout:
                print(f"Output: {stdout.decode()}")
            if stderr:
                print(f"Error: {stderr.decode()}")
            ngrok_process.terminate()
            return None
            
    except Exception as e:
        print(f"Lỗi khi khởi động ngrok: {str(e)}")
        return None

def stop_ngrok():
    """Dừng tất cả các tiến trình ngrok đang chạy"""
    try:
        # Lệnh pkill/killall cho Linux/Mac
        if sys.platform.startswith("linux") or sys.platform == "darwin":
            subprocess.run(["pkill", "ngrok"], stderr=subprocess.PIPE)
        # Lệnh taskkill cho Windows
        elif sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], stderr=subprocess.PIPE)
        
        print("Đã dừng tất cả các tiến trình ngrok")
        return True
    except Exception as e:
        print(f"Lỗi khi dừng ngrok: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Thiết lập và quản lý ngrok tunnel')
    parser.add_argument('--port', type=int, default=80, help='Port để tạo tunnel (mặc định: 80)')
    parser.add_argument('--ngrok-path', default=NGROK_DEFAULT_PATH, help=f'Đường dẫn đến ngrok binary (mặc định: {NGROK_DEFAULT_PATH})')
    parser.add_argument('--region', help='Khu vực server ngrok (vd: us, eu, au, ap, sa, jp, in)')
    parser.add_argument('--domain', help='Tên miền tùy chỉnh nếu bạn đang sử dụng ngrok Pro/Business')
    parser.add_argument('--authtoken', help='Token xác thực ngrok, nếu chưa được cấu hình')
    parser.add_argument('--stop', action='store_true', help='Dừng tất cả các tiến trình ngrok đang chạy')
    
    args = parser.parse_args()
    
    if args.stop:
        stop_ngrok()
        return
    
    url = start_ngrok(
        port=args.port,
        ngrok_path=args.ngrok_path,
        region=args.region,
        domain=args.domain,
        authtoken=args.authtoken
    )
    
    if url:
        print(f"Đường dẫn HLS: {url}/playlist.m3u8")
        
        # Giữ script chạy để ngrok không bị dừng
        print("Đang giữ ngrok chạy... Nhấn Ctrl+C để dừng.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Đã nhận tín hiệu dừng, đang dừng ngrok...")
            stop_ngrok()
    else:
        print("Không thể khởi động ngrok tunnel.")

if __name__ == "__main__":
    main()