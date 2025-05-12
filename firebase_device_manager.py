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
    Thử khởi động ngrok nếu không đang chạy
    
    Returns:
        bool: True nếu ngrok đã được khởi động thành công, False nếu không
    """
    if is_ngrok_running():
        return True
        
    # Kiểm tra xem ngrok đã được cài đặt chưa
    if not os.path.exists(ngrok_path):
        print(f"Không tìm thấy ngrok tại {ngrok_path}")
        print("Vui lòng cài đặt ngrok hoặc chỉ định đường dẫn đúng")
        return False
    
    try:
        # Chạy ngrok dưới dạng tiến trình nền
        cmd = [ngrok_path, "http", str(port)]
        ngrok_process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
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

def register_device(device_uuid, id_token, ngrok_url=None):
    """
    Đăng ký thiết bị mới vào Firestore nếu chưa tồn tại
    
    Args:
        device_uuid (str): UUID của thiết bị
        id_token (str): Firebase ID token để xác thực
        ngrok_url (str, optional): URL ngrok public
        
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
    
    # Biến lưu trữ createdAt từ document hiện có nếu có
    created_at = None
    if exists and device_data and "fields" in device_data:
        if "createdAt" in device_data["fields"]:
            created_at = device_data["fields"]["createdAt"]
            print(f"Sử dụng giá trị createdAt hiện có: {created_at.get('timestampValue')}")
    
    # Kiểm tra xem có document nào khác có cùng thuộc tính của thiết bị này không
    # bằng cách thực hiện truy vấn tìm kiếm
    query_url = f"{FIREBASE_FIRESTORE_URL}:runQuery"
    query_data = {
        "structuredQuery": {
            "from": [{"collectionId": "devices"}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "id"},
                    "op": "EQUAL",
                    "value": {"stringValue": device_uuid}
                }
            },
            "limit": 1
        }
    }
    
    # Biến lưu trữ các trường đã hợp nhất từ document trùng lặp
    merged_fields = {}
    
    try:
        response = requests.post(query_url, json=query_data, headers=headers)
        if response.status_code == 200:
            results = response.json()
            existing_doc_with_same_id = None
            
            # Kiểm tra xem có document nào khác trong kết quả không
            for result in results:
                if "document" in result:
                    doc_path = result["document"]["name"]
                    doc_id = doc_path.split("/")[-1]
                    if doc_id != device_uuid:  # Nếu ID khác với UUID, đây là document cần hợp nhất
                        existing_doc_with_same_id = doc_id
                        print(f"Tìm thấy document trùng lặp với ID: {existing_doc_with_same_id}")
                        break
            
            # Nếu tìm thấy document trùng lặp, xóa nó sau khi hợp nhất dữ liệu
            if existing_doc_with_same_id:
                # Lấy dữ liệu từ document trùng lặp
                duplicate_doc_url = f"{FIREBASE_FIRESTORE_URL}/devices/{existing_doc_with_same_id}"
                dup_response = requests.get(duplicate_doc_url, headers=headers)
                if dup_response.status_code == 200:
                    dup_data = dup_response.json()
                    
                    # Hợp nhất dữ liệu để dùng cho document UUID
                    if "fields" in dup_data:
                        for field, value in dup_data["fields"].items():
                            if field != "id":  # Không lấy trường ID từ document trùng lặp
                                merged_fields[field] = value
                                
                                # Lấy createdAt từ document trùng lặp nếu chưa có
                                if field == "createdAt" and not created_at:
                                    created_at = value
                                    print(f"Sử dụng createdAt từ document trùng lặp: {value.get('timestampValue')}")
                    
                    # Xóa document trùng lặp
                    delete_url = f"{FIREBASE_FIRESTORE_URL}:commit"
                    delete_payload = {
                        "writes": [{
                            "delete": f"projects/{PROJECT_ID}/databases/(default)/documents/devices/{existing_doc_with_same_id}"
                        }]
                    }
                    requests.post(delete_url, json=delete_payload, headers=headers)
                    print(f"Đã xóa document trùng lặp: {existing_doc_with_same_id}")
                    
                    # Cập nhật trạng thái thiết bị để biết rằng cần hợp nhất dữ liệu
                    exists = exists or len(merged_fields) > 0
    except Exception as e:
        print(f"Lỗi khi kiểm tra document trùng lặp: {str(e)}")
    
    if exists:
        # Nếu thiết bị đã tồn tại, chỉ cập nhật URI và updatedAt
        print("Cập nhật thông tin cho thiết bị đã tồn tại")
        
        update_data = {
            "fields": {
                "updatedAt": {"timestampValue": current_time}
            }
        }
        
        # Thêm URI nếu có
        if ngrok_url:
            update_data["fields"]["uri"] = {"stringValue": ngrok_url}
        
        # Thêm các trường từ document trùng lặp (nếu có) khi cần thiết
        for field, value in merged_fields.items():
            # Không cập nhật trường updatedAt từ document trùng lặp
            if field != "updatedAt" and field != "uri":
                update_data["fields"][field] = value
        
        # Đảm bảo luôn có createdAt, sử dụng thời gian hiện tại nếu không có giá trị nào trước đó
        if not created_at:
            update_data["fields"]["createdAt"] = {"timestampValue": current_time}
        
        # Sử dụng phương thức PATCH để cập nhật một số trường
        document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
        try:
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
        
        device_data = {
            "fields": {
                "id": {"stringValue": device_uuid},
                "createdAt": {"timestampValue": current_time},  # Luôn đặt createdAt khi tạo mới
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
    
    # Trước khi cập nhật, lấy document hiện tại để đảm bảo giữ lại các trường
    document_url = f"{FIREBASE_FIRESTORE_URL}/devices/{device_uuid}"
    
    try:
        # Lấy document hiện tại
        get_response = requests.get(document_url, headers=headers)
        
        if get_response.status_code == 200:
            current_data = get_response.json()
            
            # Tạo dữ liệu cập nhật với tất cả các trường hiện có
            update_data = {"fields": {}}
            
            if "fields" in current_data:
                # Sao chép tất cả các trường hiện có
                for field, value in current_data["fields"].items():
                    update_data["fields"][field] = value
            
            # Cập nhật các trường mới
            update_data["fields"]["isOnline"] = {"booleanValue": is_online}
            update_data["fields"]["updatedAt"] = {"timestampValue": current_time}
            
            # Thêm URI nếu được cung cấp
            if ngrok_url:
                update_data["fields"]["uri"] = {"stringValue": ngrok_url}
            
            # Sử dụng phương thức PATCH để cập nhật
            response = requests.patch(document_url, json=update_data, headers=headers)
            
            if response.status_code >= 200 and response.status_code < 300:
                status = "online" if is_online else "offline"
                print(f"Cập nhật trạng thái {status} thành công cho thiết bị với ID: {device_uuid}")
                return True
            else:
                print(f"Lỗi khi cập nhật trạng thái thiết bị: {response.text}")
                return False
        else:
            print(f"Không thể lấy dữ liệu hiện tại của thiết bị: {get_response.text}")
            return False
    except Exception as e:
        print(f"Lỗi khi cập nhật trạng thái thiết bị: {str(e)}")
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