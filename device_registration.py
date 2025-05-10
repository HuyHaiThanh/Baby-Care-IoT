#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import json
import uuid
from datetime import datetime
import socket
import dotenv

# Load environment variables from .env file
dotenv.load_dotenv()

# Lấy thông tin xác thực Firebase từ biến môi trường
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

def get_device_id():
    """
    Tạo hoặc đọc device ID từ file cấu hình.
    DeviceID này sẽ được lưu lại để không tạo mới mỗi khi khởi động.
    """
    config_file = "device_config.json"
    
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            config = json.load(f)
            return config.get("device_id")
    
    # Tạo ID mới nếu chưa có
    device_id = str(uuid.uuid4())
    
    # Lưu ID vào file cấu hình
    with open(config_file, "w") as f:
        json.dump({"device_id": device_id}, f)
    
    return device_id

def get_unique_id():
    """
    Tạo một ID duy nhất khác với device ID
    """
    return str(uuid.uuid4())

def get_device_name():
    """Lấy tên thiết bị từ hostname của Raspberry Pi"""
    return socket.gethostname()

def authenticate_firebase():
    """
    Xác thực với Firebase Authentication và trả về ID token
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

def check_device_exists(device_id, user_id, headers):
    """
    Kiểm tra xem thiết bị đã được đăng ký cho người dùng này chưa
    Trả về True nếu đã tồn tại, False nếu chưa
    """
    # Kiểm tra sự tồn tại của document trực tiếp
    document_url = f"{FIREBASE_FIRESTORE_URL}/connections/{device_id}"
    try:
        response = requests.get(document_url, headers=headers)
        
        if response.status_code == 200:
            # Kiểm tra thêm xem document thuộc về user này không
            document_data = response.json()
            if "fields" in document_data:
                if "userId" in document_data["fields"]:
                    stored_user_id = document_data["fields"]["userId"]["stringValue"]
                    if stored_user_id == user_id:
                        print(f"Thiết bị với ID {device_id} đã được đăng ký cho người dùng này.")
                        return True
                    else:
                        print(f"Thiết bị với ID {device_id} đã tồn tại nhưng thuộc về người dùng khác.")
            print(f"Document với ID {device_id} đã tồn tại trong collection connections.")
            return True
        return False
    except Exception as e:
        print(f"Lỗi khi kiểm tra thiết bị: {str(e)}")
        return False

def register_device(id_token, user_id):
    """
    Đăng ký thông tin thiết bị vào Firestore
    """
    device_id = get_device_id()
    unique_id = get_unique_id()
    device_name = get_device_name()
    current_time = datetime.utcnow().isoformat() + "Z"  # Format thời gian theo chuẩn ISO 8601
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    # Kiểm tra xem thiết bị này đã được đăng ký chưa
    if check_device_exists(device_id, user_id, headers):
        return True
    
    # Dữ liệu đăng ký thiết bị (id khác với deviceId)
    device_data = {
        "fields": {
            "id": {"stringValue": unique_id},
            "deviceId": {"stringValue": device_id},
            "name": {"stringValue": device_name},
            "userId": {"stringValue": user_id},
            "createdAt": {"timestampValue": current_time}
        }
    }
    
    try:
        print(f"Đăng ký thiết bị mới với deviceId: {device_id}")
        
        # Sử dụng phương pháp commit API đã được xác nhận hoạt động
        commit_url = f"{FIREBASE_FIRESTORE_URL}:commit"
        commit_payload = {
            "writes": [{
                "update": {
                    "name": f"projects/{PROJECT_ID}/databases/(default)/documents/connections/{device_id}",
                    "fields": device_data["fields"]
                }
            }]
        }
        
        response = requests.post(commit_url, json=commit_payload, headers=headers)
        
        if response.status_code >= 200 and response.status_code < 300:
            print(f"Đăng ký thiết bị thành công với deviceId: {device_id}")
            return True
        else:
            print(f"Lỗi khi đăng ký thiết bị: {response.text}")
            return False
    except Exception as e:
        print(f"Lỗi khi đăng ký thiết bị: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("Bắt đầu đăng ký thiết bị với Firebase...")
    
    # Xác thực
    auth_result = authenticate_firebase()
    if not auth_result:
        print("Không thể xác thực với Firebase. Vui lòng kiểm tra thông tin đăng nhập.")
        return
    
    id_token, user_id = auth_result
    
    # Đăng ký thiết bị
    register_device(id_token, user_id)

if __name__ == "__main__":
    main()