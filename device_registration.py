#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import json
import uuid
from datetime import datetime
import socket

# Thông tin xác thực Firebase (sẽ thay thế bằng thông tin thực tế của bạn)
API_KEY = "AIzaSyBGS8Ce_W4i91LXiR3ZcFp_QN5FOfojHhQ"
EMAIL = "iotuser01@email.com"
PASSWORD = "huyht2004"
PROJECT_ID = "babycare-81f74"

# URL cho các API của Firebase
FIREBASE_AUTH_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
# URL chính xác cho Firestore API
FIREBASE_FIRESTORE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

def get_device_id():
    """
    Tạo hoặc đọc ID thiết bị từ file cấu hình.
    ID này sẽ được lưu lại để không tạo mới mỗi khi khởi động.
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
        
        # Hiển thị chi tiết phản hồi để gỡ lỗi
        print(f"Mã trạng thái xác thực: {response.status_code}")
        
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

def register_device(id_token, user_id):
    """
    Đăng ký thông tin thiết bị vào Firestore
    """
    device_id = get_device_id()
    device_name = get_device_name()
    current_time = datetime.utcnow().isoformat() + "Z"  # Format thời gian theo chuẩn ISO 8601
    
    # Dữ liệu đăng ký thiết bị
    device_data = {
        "fields": {
            "id": {"stringValue": device_id},
            "deviceId": {"stringValue": device_id},
            "name": {"stringValue": device_name},
            "userId": {"stringValue": user_id},
            "createdAt": {"timestampValue": current_time}
        }
    }
    
    # Tạo URL chính xác cho collection và document
    document_url = f"{FIREBASE_FIRESTORE_URL}/connections/{device_id}"
    
    # Header với ID token
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Kiểm tra thiết bị với ID: {device_id}")
        print(f"URL yêu cầu: {document_url}")
        
        # Kiểm tra xem thiết bị đã đăng ký chưa
        check_response = requests.get(document_url, headers=headers)
        print(f"Mã phản hồi kiểm tra: {check_response.status_code}")
        
        if check_response.status_code == 200:
            print(f"Thiết bị với ID {device_id} đã được đăng ký trước đó.")
            return True
        
        # Nếu document chưa tồn tại, tạo mới
        print(f"Tạo document mới với ID: {device_id}")
        
        # Sử dụng phương thức POST cho collection
        collection_url = f"{FIREBASE_FIRESTORE_URL}/connections"
        document_data = {
            "fields": device_data["fields"],
            "name": f"projects/{PROJECT_ID}/databases/(default)/documents/connections/{device_id}"
        }
        response = requests.post(collection_url, json=device_data, headers=headers)
        
        print(f"Mã phản hồi đăng ký: {response.status_code}")
        if response.status_code >= 200 and response.status_code < 300:
            print(f"Đăng ký thiết bị thành công với ID: {device_id}")
            return True
        else:
            print(f"Lỗi khi đăng ký thiết bị: {response.text}")
            
            # Thử phương pháp thay thế nếu POST không thành công
            print("Thử phương pháp thay thế...")
            alt_url = f"{FIREBASE_FIRESTORE_URL}:commit"
            alt_payload = {
                "writes": [{
                    "update": {
                        "name": f"projects/{PROJECT_ID}/databases/(default)/documents/connections/{device_id}",
                        "fields": device_data["fields"]
                    }
                }]
            }
            alt_response = requests.post(alt_url, json=alt_payload, headers=headers)
            print(f"Mã phản hồi phương pháp thay thế: {alt_response.status_code}")
            
            if alt_response.status_code >= 200 and alt_response.status_code < 300:
                print(f"Đăng ký thiết bị thành công với phương pháp thay thế. ID: {device_id}")
                return True
            else:
                print(f"Lỗi khi sử dụng phương pháp thay thế: {alt_response.text}")
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