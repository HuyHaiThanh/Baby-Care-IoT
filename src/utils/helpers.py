# File: src/utils/helpers.py
# Module chứa các hàm tiện ích chung

import os
import time
import datetime
import requests
import json
import socket
from ..core.config import DEVICE_NAME, DEVICE_ID, CONNECTION_TIMEOUT, MAX_RETRIES, RETRY_DELAY
from .logger import logger

def get_ip_addresses():
    """
    Lấy danh sách địa chỉ IP của thiết bị (trừ loopback)
    
    Returns:
        dict: Dictionary chứa tên interface và địa chỉ IP
    """
    ip_list = {}
    
    try:
        # Sử dụng socket để lấy IP địa chỉ chính
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        main_ip = s.getsockname()[0]
        s.close()
        ip_list["default"] = main_ip
        
        # Thêm localhost nếu cần
        if main_ip != "127.0.0.1":
            ip_list["localhost"] = "127.0.0.1"
            
    except Exception as e:
        logger.warning(f"Không thể lấy địa chỉ IP: {e}")
        # Fallback về localhost
        ip_list["localhost"] = "127.0.0.1"
        
    return ip_list

def get_device_info():
    """Lấy thông tin về thiết bị Raspberry Pi"""
    device_info = {
        "device_id": DEVICE_ID,
        "system_info": {}
    }
    
    try:
        # Lấy thông tin về CPU
        with open('/proc/cpuinfo', 'r') as f:
            cpu_info = f.read()
            
            # Tìm model của Raspberry Pi
            for line in cpu_info.splitlines():
                if 'Model' in line:
                    device_info['system_info']['model'] = line.split(':')[1].strip()
                    break
            
        # Lấy thông tin RAM
        try:
            with open('/proc/meminfo', 'r') as f:
                mem_info = f.read()
                for line in mem_info.splitlines():
                    if 'MemTotal' in line:
                        mem_total = line.split(':')[1].strip()
                        device_info['system_info']['memory'] = mem_total
                        break
        except:
            pass
            
        # Lấy nhiệt độ CPU nếu có thể
        try:
            temp = os.popen("vcgencmd measure_temp").readline()
            device_info['system_info']['temperature'] = temp.replace("temp=", "").strip()
        except:
            pass
            
    except Exception as e:
        logger.warning(f"Không thể lấy thông tin thiết bị: {e}")
    
    return device_info

def get_timestamp():
    """
    Lấy timestamp hiện tại dưới dạng chuỗi và float
    
    Returns:
        tuple: (string_timestamp, float_timestamp)
    """
    now = datetime.datetime.now()
    string_timestamp = now.strftime("%Y%m%d_%H%M%S")
    float_timestamp = time.time()
    return string_timestamp, float_timestamp

def make_api_request(url, method='GET', data=None, files=None, headers=None, json_data=None):
    """
    Thực hiện yêu cầu API với xử lý retry và lỗi
    
    Args:
        url (str): URL API endpoint
        method (str): Phương thức HTTP ('GET', 'POST', etc.)
        data (dict): Dữ liệu form để gửi đi
        files (dict): Các file cần upload
        headers (dict): Headers HTTP tùy chỉnh
        json_data (dict): Dữ liệu JSON để gửi đi
        
    Returns:
        tuple: (success, response_or_error)
            - success: True nếu yêu cầu thành công, False nếu không
            - response_or_error: Dữ liệu JSON phản hồi hoặc thông báo lỗi
    """
    if headers is None:
        headers = {}
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Thêm thông tin thiết bị vào headers
            headers['X-Device-ID'] = DEVICE_ID
            
            # Thực hiện yêu cầu HTTP
            response = requests.request(
                method=method,
                url=url,
                data=data,
                json=json_data,
                files=files,
                headers=headers,
                timeout=CONNECTION_TIMEOUT
            )
            
            # Kiểm tra trạng thái phản hồi
            response.raise_for_status()
            
            # Phân tích phản hồi JSON nếu có
            try:
                return True, response.json()
            except ValueError:
                # Không phải JSON, trả về text
                return True, response.text
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Lỗi kết nối tới {url}: {e}"
            logger.error(error_msg)
            
            # Đợi một lát trước khi thử lại
            retry_count += 1
            if retry_count < MAX_RETRIES:
                logger.info(f"Đang thử lại lần {retry_count}/{MAX_RETRIES} sau {RETRY_DELAY} giây...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"Đã thử lại {MAX_RETRIES} lần nhưng không thành công")
                return False, f"Lỗi sau {MAX_RETRIES} lần thử: {e}"
    
    return False, f"Không thể kết nối đến server sau {MAX_RETRIES} lần thử"

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
