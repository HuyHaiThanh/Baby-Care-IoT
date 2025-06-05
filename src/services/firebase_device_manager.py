#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import json
import uuid
from datetime import datetime
import dotenv
import subprocess
import sys
import time
import argparse

# Load environment variables từ file .env
dotenv.load_dotenv()

# Lấy thông tin cấu hình Firebase từ biến môi trường
API_KEY = os.getenv('API_KEY')
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
PROJECT_ID = os.getenv('PROJECT_ID')

# Đường dẫn mặc định đến file cấu hình ngrok
DEFAULT_NGROK_PATH = "/usr/local/bin/ngrok"

# Kiểm tra xem có đủ thông tin cần thiết không
if not all([API_KEY, EMAIL, PASSWORD, PROJECT_ID]):
    print("Thiếu thông tin cấu hình Firebase!")
    print("Vui lòng tạo file .env với các thông tin sau:")
    print("API_KEY=YOUR_FIREBASE_API_KEY")
    print("EMAIL=YOUR_EMAIL@example.com")
    print("PASSWORD=YOUR_PASSWORD")
    print("PROJECT_ID=YOUR_PROJECT_ID")
    exit(1)

# URL cho các API của Firebase
FIREBASE_AUTH_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
FIREBASE_FIRESTORE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# Đường dẫn file lưu UUID của thiết bị (relative to project root)
DEVICE_UUID_FILE = "device_uuid.json"

def get_device_uuid():
    """
    Lấy hoặc tạo UUID cho thiết bị.
    UUID này sẽ được lưu vào file để sử dụng nhất quán giữa các lần khởi động.
    
    Returns:
        str: UUID của thiết bị dưới dạng string
    """
    if os.path.exists(DEVICE_UUID_FILE):
        try:
            with open(DEVICE_UUID_FILE, 'r') as f:
                data = json.load(f)
                return data.get('device_uuid')
        except:
            pass
    
    # Tạo UUID mới nếu chưa tồn tại hoặc lỗi đọc file
    new_uuid = str(uuid.uuid4())
    
    try:
        with open(DEVICE_UUID_FILE, 'w') as f:
            json.dump({'device_uuid': new_uuid}, f)
        print(f"Đã tạo UUID mới cho thiết bị: {new_uuid}")
    except Exception as e:
        print(f"Không thể lưu UUID vào file: {e}")
        
    return new_uuid

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

def start_ngrok(port=80, ngrok_path=DEFAULT_NGROK_PATH):
    """
    Khởi động ngrok với port được chỉ định
    
    Args:
        port (int): Port để tunneling
        ngrok_path (str): Đường dẫn đến ngrok binary
        
    Returns:
        bool: True nếu thành công khởi động, False nếu thất bại
    """
    try:
        if is_ngrok_running():
            print("Ngrok đã đang chạy")
            return True
            
        # Khởi động ngrok
        cmd = [ngrok_path, "http", str(port)]
        print(f"Khởi động ngrok với lệnh: {' '.join(cmd)}")
        
        # Chạy ngrok trong background
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Đợi để ngrok khởi động
        print("Đang khởi động ngrok...")
        for _ in range(5):  # Thử trong 5 giây
            time.sleep(1)
            if is_ngrok_running():
                print("Ngrok đã khởi động thành công")
                return True
        
        print("Không thể khởi động ngrok sau 5 giây")
        return False
            
    except Exception as e:
        print(f"Lỗi khi khởi động ngrok: {str(e)}")
        return False

def get_ngrok_url():
    """
    Lấy URL public của ngrok từ API cục bộ.
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    try:
        # Truy vấn API cục bộ của ngrok để lấy URL public
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=3)
        if response.status_code == 200:
            data = response.json()
            # Tìm tunnel HTTPS hoặc HTTP
            for tunnel in data.get('tunnels', []):
                if tunnel.get('proto') == 'https':
                    return tunnel.get('public_url')
                elif tunnel.get('proto') == 'http':
                    return tunnel.get('public_url')
            
            # Nếu không tìm thấy tunnel nào
            if data.get('tunnels'):
                return data['tunnels'][0].get('public_url')
        
        print(f"Không tìm thấy URL ngrok. Mã trạng thái: {response.status_code}")
        return None
    except Exception as e:
        print(f"Lỗi khi lấy URL ngrok: {e}")
        return None

def authenticate_firebase():
    """
    Xác thực với Firebase và lấy ID token
    
    Returns:
        tuple: (id_token, user_id) nếu thành công, None nếu thất bại
    """
    auth_payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "returnSecureToken": True
    }
    
    try:
        response = requests.post(FIREBASE_AUTH_URL, json=auth_payload)
        
        if response.status_code == 200:
            auth_data = response.json()
            id_token = auth_data.get('idToken')
            user_id = auth_data.get('localId')
            print("Xác thực Firebase thành công")
            return id_token, user_id
        else:
            print(f"Lỗi xác thực Firebase: {response.text}")
            return None
    except Exception as e:
        print(f"Lỗi kết nối Firebase: {str(e)}")
        return None

def check_device_exists(device_uuid, id_token):
    """
    Kiểm tra xem thiết bị đã tồn tại trong Firestore chưa
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        
    Returns:
        tuple: (exists: bool, device_data: dict hoặc None)
    """
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
    headers = {
        "Authorization": f"Bearer {id_token}"
    }
    
    try:
        response = requests.get(document_url, headers=headers)
        
        if response.status_code == 200:
            device_data = response.json()
            return True, device_data
        elif response.status_code == 404:
            return False, None
        else:
            print(f"Lỗi khi kiểm tra thiết bị: {response.text}")
            return False, None
    except Exception as e:
        print(f"Lỗi kết nối khi kiểm tra thiết bị: {str(e)}")
        return False, None

def register_device(device_uuid, id_token, ngrok_url=None):
    """
    Đăng ký hoặc cập nhật thiết bị trong Firestore
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        ngrok_url (str, optional): URL ngrok để streaming
        
    Returns:
        bool: True nếu thành công, False nếu thất bại
    """
    # Kiểm tra thiết bị hiện có
    exists, device_data = check_device_exists(device_uuid, id_token)
    
    # Thời gian hiện tại theo định dạng ISO (chuẩn Firebase timestamp)
    current_time = datetime.utcnow().isoformat() + "Z"
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Cấu hình mặc định cho device mới
    default_fields = {
        "cryingThreshold": {"integerValue": "40"},
        "noBlanketThreshold": {"integerValue": "150"},
        "proneThreshold": {"integerValue": "25"},
        "sideThreshold": {"integerValue": "30"},
        "isOnline": {"booleanValue": True},
        "updatedAt": {"timestampValue": current_time},
        "uri": {"stringValue": ""}
    }
    
    # Xử lý ngrok_url để thêm đuôi playlist.m3u8
    if ngrok_url:
        streaming_url = ngrok_url
        if not streaming_url.endswith('/playlist.m3u8'):
            streaming_url = f"{ngrok_url}/playlist.m3u8"
        default_fields["uri"]["stringValue"] = streaming_url
    
    # Giữ lại các giá trị cấu hình hiện có
    existing_fields = {}
    if exists and device_data and "fields" in device_data:
        for field in ["cryingThreshold", "noBlanketThreshold", "proneThreshold", "sideThreshold"]:
            if field in device_data["fields"]:
                existing_fields[field] = device_data["fields"][field]
    
    if exists:
        # Nếu thiết bị đã tồn tại, chỉ cập nhật URI và updatedAt
        print("Cập nhật thông tin cho thiết bị đã tồn tại")
        
        # Ưu tiên sử dụng giá trị hiện có, nếu không có thì sử dụng giá trị mặc định
        update_fields = {}
        
        # Giữ lại các trường cấu hình hiện có
        for field, value in existing_fields.items():
            update_fields[field] = value
        
        # Cập nhật các trường cần thiết
        update_fields["updatedAt"] = {"timestampValue": current_time}
        
        # Thêm URI nếu có
        if ngrok_url:
            # Thêm đuôi playlist.m3u8 nếu chưa có
            streaming_url = ngrok_url
            if not streaming_url.endswith('/playlist.m3u8'):
                streaming_url = f"{ngrok_url}/playlist.m3u8"
            update_fields["uri"] = {"stringValue": streaming_url}
        
        # Thêm các trường mặc định nếu chưa có
        for field, value in default_fields.items():
            if field not in update_fields and field not in ["updatedAt", "uri"]:
                update_fields[field] = value
        
        # Sử dụng phương thức PATCH để cập nhật tất cả các trường
        document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
        try:
            # Tạo danh sách các trường cần cập nhật cho updateMask
            field_paths = list(update_fields.keys())
            
            # URL với updateMask để chỉ cập nhật các trường được chỉ định
            query_params = "&".join([f"updateMask.fieldPaths={field}" for field in field_paths])
            document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}?{query_params}"
            
            update_data = {"fields": update_fields}
            
            response = requests.patch(document_url, json=update_data, headers=headers)
            
            if response.status_code >= 200 and response.status_code < 300:
                print(f"Cập nhật thành công thông tin cho thiết bị với ID: {device_uuid}")
                return True
            else:
                print(f"Lỗi khi cập nhật thiết bị: {response.text}")
                return False
        except Exception as e:
            print(f"Lỗi khi cập nhật thiết bị: {str(e)}")
            return False
    else:
        # Nếu thiết bị chưa tồn tại, tạo document mới
        print("Đăng ký thiết bị mới")
        
        # Tạo device_data với các trường mặc định
        device_fields = default_fields.copy()
        device_fields["id"] = {"stringValue": device_uuid}
        device_fields["updatedAt"] = {"timestampValue": current_time}
        
        # Xử lý ngrok_url để thêm đuôi playlist.m3u8
        if ngrok_url:
            streaming_url = ngrok_url
            if not streaming_url.endswith('/playlist.m3u8'):
                streaming_url = f"{ngrok_url}/playlist.m3u8"
            device_fields["uri"] = {"stringValue": streaming_url}
        else:
            device_fields["uri"] = {"stringValue": ""}
        
        # Tạo document với ID = deviceId
        try:
            # Sử dụng API commit của Firestore để tạo document với ID cụ thể
            commit_url = f"{FIREBASE_FIRESTORE_URL}:commit"
            commit_payload = {
                "writes": [{
                    "update": {
                        "name": f"projects/{PROJECT_ID}/databases/(default)/documents/devices/{device_uuid}",
                        "fields": device_fields
                    }
                }]
            }
            
            response = requests.post(commit_url, json=commit_payload, headers=headers)
            
            if response.status_code >= 200 and response.status_code < 300:
                print(f"Đăng ký thiết bị thành công với ID: {device_uuid}")
                return True
            else:
                print(f"Lỗi khi đăng ký thiết bị: {response.text}")
                return False
        except Exception as e:
            print(f"Lỗi khi đăng ký thiết bị: {str(e)}")
            return False

def update_streaming_status(device_uuid, id_token, is_online=False, ngrok_url=None):
    """
    Cập nhật trạng thái streaming của thiết bị
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        is_online (bool): Trạng thái online (True/False)
        ngrok_url (str, optional): URL ngrok nếu cần cập nhật
        
    Returns:
        bool: True nếu thành công, False nếu thất bại
    """
    # Kiểm tra thiết bị hiện có và lấy thông tin
    exists, device_data = check_device_exists(device_uuid, id_token)
    
    if not exists:
        print(f"Không tìm thấy thiết bị với ID {device_uuid}")
        return False
    
    # Thời gian hiện tại theo định dạng ISO (chuẩn Firebase timestamp)
    current_time = datetime.utcnow().isoformat() + "Z"
    
    # Trường cần cập nhật
    fields_to_update = {
        "isOnline": {"booleanValue": is_online},
        "updatedAt": {"timestampValue": current_time}
    }
    
    # Thêm URI nếu được cung cấp
    if ngrok_url:
        # Thêm đuôi playlist.m3u8 nếu chưa có
        streaming_url = ngrok_url
        if not streaming_url.endswith('/playlist.m3u8'):
            streaming_url = f"{ngrok_url}/playlist.m3u8"
        fields_to_update["uri"] = {"stringValue": streaming_url}
        
    # Bảo toàn các trường threshold từ thiết bị hiện có
    if exists and device_data and "fields" in device_data:
        for field in ["cryingThreshold", "noBlanketThreshold", "proneThreshold", "sideThreshold"]:
            if field in device_data["fields"]:
                fields_to_update[field] = device_data["fields"][field]
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Tạo danh sách các trường cần cập nhật cho updateMask
    field_paths = list(fields_to_update.keys())
    
    # URL với updateMask để chỉ cập nhật các trường được chỉ định
    query_params = "&".join([f"updateMask.fieldPaths={field}" for field in field_paths])
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}?{query_params}"
    
    try:
        # Tạo dữ liệu cập nhật với định dạng đúng cho Firestore
        update_data = {"fields": fields_to_update}
        
        # Sử dụng PATCH với updateMask
        response = requests.patch(document_url, json=update_data, headers=headers)
        
        if response.status_code >= 200 and response.status_code < 300:
            status = "online" if is_online else "offline"
            print(f"Cập nhật trạng thái {status} thành công cho thiết bị với ID: {device_uuid}")
            return True
        else:
            print(f"Lỗi khi cập nhật trường: {response.text}")
            return False
    except Exception as e:
        print(f"Lỗi khi cập nhật document: {str(e)}")
        return False

def update_document_fields(device_uuid, id_token, fields_to_update):
    """
    Cập nhật các trường cụ thể trong document thiết bị
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        fields_to_update (dict): Các trường cần cập nhật
        
    Returns:
        bool: True nếu thành công, False nếu thất bại
    """
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Tạo danh sách các trường cần cập nhật cho updateMask
    field_paths = list(fields_to_update.keys())
    
    # URL với updateMask để chỉ cập nhật các trường được chỉ định
    query_params = "&".join([f"updateMask.fieldPaths={field}" for field in field_paths])
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}?{query_params}"
    
    try:
        # Tạo dữ liệu cập nhật với định dạng đúng cho Firestore
        update_data = {"fields": fields_to_update}
        
        # Sử dụng PATCH với updateMask
        response = requests.patch(document_url, json=update_data, headers=headers)
        
        if response.status_code >= 200 and response.status_code < 300:
            print(f"Cập nhật thành công các trường {', '.join(field_paths)} cho thiết bị {device_uuid}")
            return True
        else:
            print(f"Lỗi khi cập nhật trường: {response.text}")
            return False
    except Exception as e:
        print(f"Lỗi khi cập nhật document: {str(e)}")
        return False

def initialize_device(start_ngrok_if_needed=True, ngrok_path=DEFAULT_NGROK_PATH):
    """
    Khởi tạo và đăng ký thiết bị khi khởi động
    
    Args:
        start_ngrok_if_needed (bool): Tự động khởi động ngrok nếu chưa chạy
        ngrok_path (str): Đường dẫn đến ngrok binary
        
    Returns:
        tuple: (device_uuid, id_token) nếu thành công
    """
    # Xác thực với Firebase
    auth_result = authenticate_firebase()
    if not auth_result:
        print("Không thể xác thực với Firebase.")
        return None, None
    
    id_token, user_id = auth_result
    
    # Lấy UUID của thiết bị
    device_uuid = get_device_uuid()
    print(f"UUID của thiết bị: {device_uuid}")
    
    # Thử khởi động ngrok nếu được yêu cầu và chưa chạy
    ngrok_started = False
    if start_ngrok_if_needed and not is_ngrok_running():
        print("ngrok chưa chạy, đang thử khởi động...")
        ngrok_started = start_ngrok(ngrok_path=ngrok_path)
    
    # Lấy URL ngrok
    ngrok_url = get_ngrok_url() if is_ngrok_running() else None
    if not ngrok_url:
        print("Không thể lấy URL ngrok. Tiếp tục với URI trống.")
    else:
        print(f"URL ngrok: {ngrok_url}")
        
    # Đăng ký hoặc cập nhật thiết bị
    success = register_device(device_uuid, id_token, ngrok_url)
    if not success:
        print("Lỗi khi đăng ký/cập nhật thiết bị.")
    
    return device_uuid, id_token

def main():
    """
    Hàm chính để khởi tạo thiết bị khi script được chạy trực tiếp
    """
    parser = argparse.ArgumentParser(description='Đăng ký thiết bị với Firebase Firestore')
    parser.add_argument('--start-ngrok', action='store_true', help='Tự động khởi động ngrok nếu chưa chạy')
    parser.add_argument('--ngrok-path', default=DEFAULT_NGROK_PATH, help='Đường dẫn đến ngrok binary')
    
    args = parser.parse_args()
    
    print("Khởi tạo thiết bị...")
    device_uuid, id_token = initialize_device(
        start_ngrok_if_needed=args.start_ngrok,
        ngrok_path=args.ngrok_path
    )
    
    if not device_uuid or not id_token:
        print("Khởi tạo thiết bị thất bại.")
        return
    
    print(f"Thiết bị đã được khởi tạo thành công với UUID: {device_uuid}")

if __name__ == "__main__":
    main()
