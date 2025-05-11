#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import json
import uuid
from datetime import datetime
import dotenv

# Load environment variables từ file .env
dotenv.load_dotenv()

# Lấy thông tin cấu hình Firebase từ biến môi trường
API_KEY = os.getenv('API_KEY')
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
PROJECT_ID = os.getenv('PROJECT_ID')

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

# Đường dẫn file lưu UUID của thiết bị
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
                if 'uuid' in data:
                    return data['uuid']
        except Exception as e:
            print(f"Lỗi khi đọc UUID từ file: {e}")
    
    # Tạo UUID mới nếu chưa có
    device_uuid = str(uuid.uuid4())
    
    # Lưu UUID vào file
    try:
        with open(DEVICE_UUID_FILE, 'w') as f:
            json.dump({'uuid': device_uuid}, f)
    except Exception as e:
        print(f"Lỗi khi lưu UUID vào file: {e}")
    
    return device_uuid

def get_ngrok_url():
    """
    Lấy URL public của ngrok từ API cục bộ.
    
    Returns:
        str: URL ngrok nếu thành công, None nếu thất bại
    """
    try:
        # Truy vấn API cục bộ của ngrok để lấy URL public
        response = requests.get("http://127.0.0.1:4040/api/tunnels")
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
    Xác thực với Firebase Authentication và trả về ID token
    
    Returns:
        tuple: (id_token, user_id) nếu thành công, None nếu thất bại
    """
    auth_data = {
        "email": EMAIL,
        "password": PASSWORD,
        "returnSecureToken": True
    }
    
    try:
        print("Đang xác thực với Firebase...")
        response = requests.post(FIREBASE_AUTH_URL, json=auth_data)
        
        if response.status_code != 200:
            print(f"Lỗi xác thực: {response.text}")
            return None
        
        auth_result = response.json()
        id_token = auth_result.get("idToken")
        user_id = auth_result.get("localId")
        
        print("Xác thực thành công!")
        return id_token, user_id
    except Exception as e:
        print(f"Lỗi khi xác thực: {str(e)}")
        return None

def check_device_exists(device_uuid, id_token):
    """
    Kiểm tra xem thiết bị đã tồn tại trong collection 'devices' chưa
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        
    Returns:
        bool: True nếu thiết bị đã tồn tại, False nếu chưa
    """
    # URL để truy cập document cụ thể
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Kiểm tra thiết bị với ID: {device_uuid}")
        response = requests.get(document_url, headers=headers)
        
        if response.status_code == 200:
            print(f"Thiết bị với ID {device_uuid} đã tồn tại.")
            return True, response.json()
        elif response.status_code == 404:
            print(f"Thiết bị với ID {device_uuid} chưa tồn tại.")
            return False, None
        else:
            print(f"Lỗi khi kiểm tra thiết bị: {response.text}")
            return False, None
    except Exception as e:
        print(f"Lỗi khi kiểm tra thiết bị: {str(e)}")
        return False, None

def register_device(device_uuid, id_token, ngrok_url):
    """
    Đăng ký thiết bị mới vào Firestore nếu chưa tồn tại
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        ngrok_url (str): URL ngrok public
        
    Returns:
        bool: True nếu thành công, False nếu thất bại
    """
    # Kiểm tra thiết bị đã tồn tại chưa
    exists, device_data = check_device_exists(device_uuid, id_token)
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Thời gian hiện tại theo định dạng ISO (chuẩn Firebase timestamp)
    current_time = datetime.utcnow().isoformat() + "Z"
    
    if exists:
        # Nếu thiết bị đã tồn tại, chỉ cập nhật URI và updatedAt
        print("Cập nhật URI và thời gian cho thiết bị đã tồn tại")
        
        update_data = {
            "fields": {
                "uri": {"stringValue": ngrok_url},
                "updatedAt": {"timestampValue": current_time}
            }
        }
        
        # Sử dụng phương thức PATCH để cập nhật một số trường
        document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
        try:
            response = requests.patch(document_url, json=update_data, headers=headers)
            
            if response.status_code >= 200 and response.status_code < 300:
                print(f"Cập nhật thành công URI cho thiết bị với ID: {device_uuid}")
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
        
        device_data = {
            "fields": {
                "id": {"stringValue": device_uuid},
                "createdAt": {"timestampValue": current_time},
                "updatedAt": {"timestampValue": current_time},
                "cryingThreshold": {"integerValue": "60"},
                "noBlanketThreshold": {"integerValue": "60"},
                "proneThreshold": {"integerValue": "30"},
                "sideThreshold": {"integerValue": "30"},
                "isOnline": {"booleanValue": False},
                "uri": {"stringValue": ngrok_url if ngrok_url else ""}
            }
        }
        
        # Tạo document với ID = deviceId
        document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
        try:
            # Sử dụng API commit của Firestore để tạo document với ID cụ thể
            commit_url = f"{FIREBASE_FIRESTORE_URL}:commit"
            commit_payload = {
                "writes": [{
                    "update": {
                        "name": f"projects/{PROJECT_ID}/databases/(default)/documents/devices/{device_uuid}",
                        "fields": device_data["fields"]
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
            import traceback
            traceback.print_exc()
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
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Thời gian hiện tại theo định dạng ISO (chuẩn Firebase timestamp)
    current_time = datetime.utcnow().isoformat() + "Z"
    
    # Dữ liệu cần cập nhật
    update_data = {
        "fields": {
            "isOnline": {"booleanValue": is_online},
            "updatedAt": {"timestampValue": current_time}
        }
    }
    
    # Thêm URI nếu được cung cấp
    if ngrok_url:
        update_data["fields"]["uri"] = {"stringValue": ngrok_url}
    
    # URL để cập nhật document
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
    
    try:
        # Sử dụng phương thức PATCH để cập nhật một số trường
        response = requests.patch(document_url, json=update_data, headers=headers)
        
        if response.status_code >= 200 and response.status_code < 300:
            status = "online" if is_online else "offline"
            print(f"Cập nhật trạng thái {status} thành công cho thiết bị với ID: {device_uuid}")
            return True
        else:
            print(f"Lỗi khi cập nhật trạng thái thiết bị: {response.text}")
            return False
    except Exception as e:
        print(f"Lỗi khi cập nhật trạng thái thiết bị: {str(e)}")
        return False

def initialize_device():
    """
    Khởi tạo và đăng ký thiết bị khi khởi động
    
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
    
    # Lấy URL ngrok
    ngrok_url = get_ngrok_url()
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
    print("Khởi tạo thiết bị...")
    device_uuid, id_token = initialize_device()
    
    if not device_uuid or not id_token:
        print("Khởi tạo thiết bị thất bại.")
        return
    
    print(f"Thiết bị đã được khởi tạo thành công với UUID: {device_uuid}")

if __name__ == "__main__":
    main()