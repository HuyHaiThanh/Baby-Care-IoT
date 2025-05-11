#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
import sys
import signal
import argparse
import json

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

def get_ngrok_url(debug=False):
    """
    Lấy URL public của ngrok từ API cục bộ.
    
    Args:
        debug (bool): Nếu True, hiển thị thông tin debug chi tiết
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # In ra dữ liệu JSON đầy đủ nếu debug được bật
            if debug:
                print(f"Phản hồi API đầy đủ: {json.dumps(data, indent=2)}")
            
            tunnels = data.get('tunnels', [])
            if debug:
                print(f"Số lượng tunnels: {len(tunnels)}")
            
            # Tìm tunnel HTTPS hoặc HTTP
            for tunnel in tunnels:
                if tunnel.get('proto') == 'https':
                    return tunnel.get('public_url')
                elif tunnel.get('proto') == 'http':
                    return tunnel.get('public_url')
            
            # Nếu không tìm thấy tunnel HTTPS/HTTP cụ thể, lấy tunnel đầu tiên
            if tunnels:
                # Lấy URL từ tunnel đầu tiên
                first_tunnel = tunnels[0]
                if debug:
                    print(f"Sử dụng tunnel đầu tiên: {first_tunnel}")
                return first_tunnel.get('public_url')
        
        print(f"Phản hồi từ API ngrok: Mã trạng thái: {response.status_code}")
        if debug and response.status_code == 200:
            # Hiển thị nội dung phản hồi để gỡ lỗi
            print("Nội dung phản hồi:")
            print(response.text)
            
        return None
    except Exception as e:
        print(f"Lỗi khi lấy URL ngrok: {str(e)}")
        return None

def start_ngrok(port=80, ngrok_path=NGROK_DEFAULT_PATH, region=None, domain=None, authtoken=None, debug=False):
    """
    Khởi động ngrok nếu chưa đang chạy
    
    Args:
        port: Port để tạo tunnel (mặc định 80 cho web server)
        ngrok_path: Đường dẫn đến ngrok binary
        region: Khu vực server ngrok (vd: us, eu, au, ap, sa, jp, in)
        domain: Tên miền tùy chỉnh nếu bạn đang sử dụng ngrok Pro/Business
        authtoken: Token xác thực ngrok, nếu chưa được cấu hình
        debug: Hiển thị thông tin gỡ lỗi chi tiết
    
    Returns:
        str: URL ngrok public hoặc None nếu có lỗi
    """
    if is_ngrok_running():
        print("ngrok đã đang chạy!")
        url = get_ngrok_url(debug)
        if url:
            print(f"URL ngrok hiện tại: {url}")
            return url
        else:
            print("ngrok đang chạy nhưng không thể lấy được URL")
            if debug:
                print("Thử kiểm tra trực tiếp từ trình duyệt: http://127.0.0.1:4040/")
            return None
        
    print("Bắt đầu khởi động ngrok...")
    
    # Kiểm tra xem ngrok có tồn tại không
    if not os.path.exists(ngrok_path):
        alternative_path = "ngrok"  # Thử sử dụng ngrok trong PATH
        try:
            subprocess.run([alternative_path, "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            ngrok_path = alternative_path
            print(f"Không tìm thấy ngrok tại {NGROK_DEFAULT_PATH}, sử dụng ngrok từ PATH")
        except:
            print(f"Không tìm thấy ngrok tại {ngrok_path}")
            print("Vui lòng cài đặt ngrok hoặc chỉ định đường dẫn đúng")
            return None
    
    # Cấu hình authtoken nếu được cung cấp
    if authtoken:
        try:
            auth_cmd = [ngrok_path, "authtoken", authtoken]
            subprocess.run(auth_cmd, check=True)
            print(f"Đã thiết lập authtoken ngrok thành công")
        except subprocess.CalledProcessError as e:
            print(f"Lỗi khi thiết lập authtoken: {str(e)}")
            if debug:
                print(f"Command: {' '.join(auth_cmd)}")
                print(f"Return code: {e.returncode}")
                if e.output:
                    print(f"Output: {e.output.decode()}")
                if e.stderr:
                    print(f"Error: {e.stderr.decode()}")
            return None
    
    # Chuẩn bị lệnh ngrok
    cmd = [ngrok_path, "http", str(port)]
    
    # Thêm các tùy chọn nếu được cung cấp
    if region:
        cmd.extend(["--region", region])
    
    if domain:
        cmd.extend(["--domain", domain])
    
    # Khởi động ngrok trong tiến trình con
    try:
        if debug:
            print(f"Lệnh khởi động ngrok: {' '.join(cmd)}")
        
        # Chạy ngrok dưới dạng tiến trình nền
        ngrok_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Đợi để ngrok khởi động
        print("Đợi ngrok khởi động...")
        for i in range(10):  # Thử trong 10 giây
            time.sleep(1)
            if debug:
                print(f"Kiểm tra ngrok lần {i+1}...")
            if is_ngrok_running():
                print("Phát hiện ngrok đang chạy")
                break
        
        if is_ngrok_running():
            # Đợi thêm 2 giây để ngrok thiết lập tunnel hoàn toàn
            time.sleep(2)
            
            url = get_ngrok_url(debug)
            if url:
                print(f"ngrok đã khởi động thành công. URL: {url}")
                return url
            else:
                if debug:
                    print("Đang kiểm tra API ngrok trực tiếp...")
                    try:
                        raw_response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
                        print(f"Mã trạng thái: {raw_response.status_code}")
                        print(f"Nội dung phản hồi: {raw_response.text}")
                    except Exception as e:
                        print(f"Không thể kết nối tới API ngrok: {str(e)}")
                
                print("ngrok đã khởi động nhưng không thể lấy được URL")
                print("Hãy thử mở http://127.0.0.1:4040 trong trình duyệt để xem giao diện của ngrok")
                return None
        else:
            print("Không thể khởi động ngrok sau nhiều lần thử")
            
            # Kiểm tra lỗi
            try:
                stdout, stderr = ngrok_process.communicate(timeout=1)
                if stdout:
                    print(f"Output: {stdout.decode()}")
                if stderr:
                    print(f"Error: {stderr.decode()}")
            except:
                pass
                
            # Thử kiểm tra xem ngrok có đang chạy không theo cách khác
            try:
                if sys.platform.startswith("linux") or sys.platform == "darwin":
                    ps_cmd = subprocess.run(["ps", "aux"], stdout=subprocess.PIPE, text=True)
                    if "ngrok" in ps_cmd.stdout:
                        print("ngrok có vẻ đang chạy nhưng không phản hồi API")
                elif sys.platform == "win32":
                    tasklist_cmd = subprocess.run(["tasklist"], stdout=subprocess.PIPE, text=True)
                    if "ngrok" in tasklist_cmd.stdout:
                        print("ngrok có vẻ đang chạy nhưng không phản hồi API")
            except:
                pass
                
            return None
            
    except Exception as e:
        print(f"Lỗi khi khởi động ngrok: {str(e)}")
        if debug:
            print(f"Traceback: {sys.exc_info()}")
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
    parser.add_argument('--debug', action='store_true', help='Hiển thị thông tin gỡ lỗi chi tiết')
    
    args = parser.parse_args()
    
    if args.stop:
        stop_ngrok()
        return
    
    url = start_ngrok(
        port=args.port,
        ngrok_path=args.ngrok_path,
        region=args.region,
        domain=args.domain,
        authtoken=args.authtoken,
        debug=args.debug
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
        print("Thử chạy với tùy chọn --debug để xem thông tin chi tiết hơn.")

if __name__ == "__main__":
    main()