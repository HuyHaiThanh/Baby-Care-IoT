# File: utils.py
# Module chứa các tiện ích và hàm trợ giúp

import os
import time
import datetime
import logging
import requests
import json
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

# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    print("Kiểm tra module utils...")
    
    # Test lấy timestamp
    string_ts, float_ts = get_timestamp()
    print(f"Timestamp hiện tại: {string_ts} ({float_ts})")
    
    # Test lấy thông tin thiết bị
    device_info = get_device_info()
    print(f"Thông tin thiết bị: {json.dumps(device_info, indent=2)}")
    
    print("Hoàn tất kiểm tra module utils")