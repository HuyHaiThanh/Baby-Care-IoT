# File: utils.py
# Các hàm tiện ích cho client Pi

import os
import time
import socket
import logging
import datetime
import json
import requests
import netifaces
from config import DEVICE_NAME, DEVICE_ID, CONNECTION_TIMEOUT, MAX_RETRIES, RETRY_DELAY

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('pi-client')

def get_ip_addresses():
    """
    Lấy danh sách địa chỉ IP của thiết bị (trừ loopback)
    
    Returns:
        dict: Dictionary chứa tên interface và địa chỉ IP
    """
    ip_list = {}
    
    try:
        # Sử dụng netifaces để lấy danh sách interfaces mạng
        interfaces = netifaces.interfaces()
        
        for interface in interfaces:
            # Bỏ qua interface loopback
            if interface == 'lo':
                continue
                
            ifaddresses = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in ifaddresses:
                for link in ifaddresses[netifaces.AF_INET]:
                    if 'addr' in link:
                        ip_list[interface] = link['addr']
    except ImportError:
        # Nếu không có netifaces, sử dụng socket
        try:
            # Kết nối đến Google DNS để lấy IP (không thực sự kết nối)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_list["default"] = s.getsockname()[0]
            s.close()
        except Exception as e:
            logger.warning(f"Không thể lấy địa chỉ IP: {e}")
    except Exception as e:
        logger.warning(f"Lỗi khi lấy địa chỉ IP: {e}")
        
    return ip_list

def make_api_request(url, method='POST', data=None, files=None, json_data=None):
    """
    Gửi yêu cầu API đến server với cơ chế thử lại
    
    Args:
        url (str): URL của API endpoint
        method (str): Phương thức HTTP (GET, POST)
        data (dict): Dữ liệu form
        files (dict): Các file cần gửi
        json_data (dict): Dữ liệu JSON
        
    Returns:
        tuple: (Thành công (bool), Phản hồi (Response hoặc Exception))
    """
    headers = {
        'X-Device-ID': DEVICE_ID,
        'X-Device-Name': DEVICE_NAME
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                data=data,
                files=files,
                json=json_data,
                headers=headers,
                timeout=CONNECTION_TIMEOUT
            )
            
            # Kiểm tra xem request có thành công hay không
            response.raise_for_status()
            
            # Trả về kết quả nếu thành công
            return True, response
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Lỗi yêu cầu API lần {attempt + 1}/{MAX_RETRIES}: {e}")
            
            # Chờ trước khi thử lại, trừ lần thử cuối cùng
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    
    # Đã hết số lần thử
    return False, Exception(f"Không thể kết nối đến {url} sau {MAX_RETRIES} lần thử")

def get_timestamp():
    """
    Lấy timestamp hiện tại dưới dạng chuỗi và số
    
    Returns:
        tuple: (string_timestamp, float_timestamp)
    """
    now = datetime.datetime.now()
    string_timestamp = now.strftime("%Y%m%d_%H%M%S")
    float_timestamp = time.time()
    return string_timestamp, float_timestamp

def check_server_status(url):
    """
    Kiểm tra trạng thái của server
    
    Args:
        url (str): URL cơ sở của server
        
    Returns:
        bool: True nếu server đang hoạt động, False nếu không
    """
    try:
        response = requests.get(f"{url}/status", timeout=CONNECTION_TIMEOUT)
        return response.status_code == 200
    except:
        return False