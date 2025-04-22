# File: websocket_server.py
# WebSocket server cho việc gửi dữ liệu âm thanh và hình ảnh theo thời gian thực

import asyncio
import websockets
import json
import base64
import datetime
import os
import time
import logging
import threading
from config import DEVICE_NAME, AUDIO_DIR, PHOTO_DIR, WEBSOCKET_PORT

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('websocket_server')

# Danh sách các kết nối WebSocket đang hoạt động
connected_clients = set()

async def send_audio_data(websocket, audio_file_path):
    """Gửi dữ liệu âm thanh qua WebSocket"""
    try:
        # Mã hóa file âm thanh thành base64
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
            base64_audio = base64.b64encode(audio_data).decode('utf-8')
        
        # Tạo timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Tạo tên file
        file_name = os.path.basename(audio_file_path)
        
        # Đóng gói message
        message = {
            "type": "audio",
            "data": base64_audio,
            "timestamp": timestamp,
            "device_name": DEVICE_NAME,
            "file_name": file_name
        }
        
        # Gửi dữ liệu
        await websocket.send(json.dumps(message))
        logger.info(f"Đã gửi dữ liệu âm thanh: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi gửi dữ liệu âm thanh: {e}")
        return False

async def send_image_data(websocket, image_file_path, quality="high"):
    """
    Gửi dữ liệu hình ảnh qua WebSocket với chất lượng tùy chỉnh
    
    Args:
        websocket: Kết nối WebSocket
        image_file_path: Đường dẫn đến file ảnh
        quality: Chất lượng ảnh ("high", "medium", "low")
    """
    try:
        from PIL import Image
        import io
        
        # Mở ảnh và nén theo chất lượng
        with Image.open(image_file_path) as img:
            # Điều chỉnh chất lượng và kích thước theo yêu cầu
            if quality == "medium":
                # Giảm kích thước xuống 50% và nén với chất lượng 70%
                new_size = (img.width // 2, img.height // 2)
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                compress_quality = 70
            elif quality == "low":
                # Giảm kích thước xuống 30% và nén với chất lượng 50%
                new_size = (img.width // 3, img.height // 3)
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                compress_quality = 50
            else:
                # Chất lượng cao - giữ nguyên kích thước, nén nhẹ
                compress_quality = 85
            
            # Lưu ảnh vào buffer với định dạng JPEG và nén
            buffer = io.BytesIO()
            img.convert('RGB').save(buffer, format="JPEG", quality=compress_quality)
            image_data = buffer.getvalue()
            
            # Mã hóa thành base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Tạo timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Tạo tên file
        file_name = os.path.basename(image_file_path)
        
        # Đóng gói message
        message = {
            "type": "image",
            "data": base64_image,
            "timestamp": timestamp,
            "device_name": DEVICE_NAME,
            "file_name": file_name,
            "quality": quality
        }
        
        # Gửi dữ liệu
        await websocket.send(json.dumps(message))
        logger.info(f"Đã gửi dữ liệu hình ảnh: {file_name} (chất lượng: {quality}, kích thước: {len(base64_image)//1024}KB)")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi gửi dữ liệu hình ảnh: {e}")
        return False

async def handle_client(websocket, path=None):
    """Xử lý kết nối từ client"""
    # Lưu client vào danh sách kết nối
    connected_clients.add(websocket)
    client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    logger.info(f"Client mới kết nối: {client_info}")
    print(f"\n===== KẾT NỐI MỚI =====")
    print(f"🔌 Client {client_info} đã kết nối")
    print(f"⌚ Thời gian: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"========================\n")
    
    try:
        # Gửi thông báo kết nối thành công
        connection_message = {
            "type": "connection",
            "status": "connected",
            "message": f"Kết nối thành công tới {DEVICE_NAME}",
            "device_name": DEVICE_NAME,
            "timestamp": datetime.datetime.now().isoformat()
        }
        await websocket.send(json.dumps(connection_message))
        
        # Vòng lặp chính để xử lý tin nhắn
        while True:
            try:
                # Nhận tin nhắn từ client
                message = await websocket.recv()
                data = json.loads(message)
                
                # In thông tin yêu cầu nhận được
                action = data.get("action", "unknown")
                print(f"\n----- YÊU CẦU TỪ CLIENT {client_info} -----")
                print(f"🔹 Hành động: {action}")
                print(f"🔹 Thời gian: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Xử lý yêu cầu từ client
                if action == "request_audio":
                    # Client yêu cầu dữ liệu âm thanh mới nhất
                    print(f"📢 YÊU CẦU ÂM THANH từ {client_info}")
                    
                    # Tìm file âm thanh mới nhất trong thư mục
                    audio_files = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) 
                                  if f.endswith('.mp3') or f.endswith('.wav')]
                    if audio_files:
                        latest_audio = max(audio_files, key=os.path.getctime)
                        file_name = os.path.basename(latest_audio)
                        file_size = os.path.getsize(latest_audio) / 1024  # KB
                        
                        print(f"🔍 Tìm thấy file âm thanh: {file_name} ({file_size:.1f} KB)")
                        print(f"📤 Đang gửi âm thanh...")
                        
                        # Gửi âm thanh
                        success = await send_audio_data(websocket, latest_audio)
                        
                        if success:
                            print(f"✅ ĐÃ GỬI THÀNH CÔNG file âm thanh: {file_name}")
                        else:
                            print(f"❌ THẤT BẠI khi gửi file âm thanh: {file_name}")
                    else:
                        print(f"❌ Không tìm thấy file âm thanh nào trong thư mục: {AUDIO_DIR}")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Không có file âm thanh nào",
                            "timestamp": datetime.datetime.now().isoformat()
                        }))
                
                elif action == "request_image":
                    # Client yêu cầu dữ liệu hình ảnh mới nhất
                    # Lấy chất lượng ảnh từ yêu cầu (mặc định là "high")
                    quality = data.get("quality", "high")
                    print(f"📷 YÊU CẦU HÌNH ẢNH từ {client_info} (Chất lượng: {quality})")
                    
                    # Kiểm tra các đường dẫn thay thế được cung cấp
                    paths = data.get("paths", [])
                    if paths:
                        print(f"🔍 Client đề xuất các đường dẫn thay thế: {', '.join(paths)}")
                    
                    image_files = []
                    
                    # Đầu tiên thử với PHOTO_DIR mặc định
                    print(f"🔍 Tìm kiếm ảnh trong thư mục mặc định: {PHOTO_DIR}")
                    default_files = [os.path.join(PHOTO_DIR, f) for f in os.listdir(PHOTO_DIR) 
                                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                    if default_files:
                        image_files = default_files
                        print(f"✅ Tìm thấy {len(default_files)} file ảnh trong thư mục mặc định")
                    
                    # Nếu không có file trong thư mục mặc định và client cung cấp đường dẫn thay thế
                    elif paths:
                        for path in paths:
                            try:
                                # Kiểm tra xem path là tương đối hay tuyệt đối
                                if os.path.isabs(path):
                                    check_path = path
                                else:
                                    check_path = os.path.normpath(os.path.join(os.path.dirname(__file__), path))
                                
                                print(f"🔍 Kiểm tra thư mục thay thế: {check_path}")
                                
                                if os.path.exists(check_path) and os.path.isdir(check_path):
                                    alt_files = [os.path.join(check_path, f) for f in os.listdir(check_path)
                                                if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                                    if alt_files:
                                        image_files = alt_files
                                        print(f"✅ Tìm thấy {len(alt_files)} file ảnh trong thư mục: {check_path}")
                                        break
                                    else:
                                        print(f"❌ Không tìm thấy file ảnh nào trong thư mục: {check_path}")
                                else:
                                    print(f"❌ Thư mục không tồn tại: {check_path}")
                            except Exception as e:
                                print(f"❌ Lỗi khi kiểm tra thư mục {path}: {e}")
                    
                    # Gửi ảnh mới nhất nếu tìm thấy
                    if image_files:
                        latest_image = max(image_files, key=os.path.getctime)
                        file_name = os.path.basename(latest_image)
                        file_size = os.path.getsize(latest_image) / 1024  # KB
                        
                        print(f"📤 Đang gửi ảnh: {file_name} ({file_size:.1f} KB) với chất lượng {quality}...")
                        
                        # Gửi ảnh
                        start_time = time.time()
                        success = await send_image_data(websocket, latest_image, quality)
                        elapsed_time = time.time() - start_time
                        
                        if success:
                            print(f"✅ ĐÃ GỬI THÀNH CÔNG file ảnh: {file_name} trong {elapsed_time:.2f} giây")
                        else:
                            print(f"❌ THẤT BẠI khi gửi file ảnh: {file_name}")
                    else:
                        print(f"❌ Không tìm thấy file ảnh nào trong bất kỳ thư mục nào")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Không có file hình ảnh nào",
                            "timestamp": datetime.datetime.now().isoformat()
                        }))
                
                elif action == "request_all":
                    # Client yêu cầu cả hình ảnh và âm thanh mới nhất
                    quality = data.get("quality", "high")
                    print(f"🔄 YÊU CẦU TẤT CẢ DỮ LIỆU từ {client_info} (Chất lượng ảnh: {quality})")
                    
                    # Xử lý âm thanh
                    audio_files = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) 
                                  if f.endswith('.mp3') or f.endswith('.wav')]
                    if audio_files:
                        latest_audio = max(audio_files, key=os.path.getctime)
                        print(f"📤 Đang gửi âm thanh: {os.path.basename(latest_audio)}...")
                        await send_audio_data(websocket, latest_audio)
                    else:
                        print(f"❌ Không tìm thấy file âm thanh nào")
                    
                    # Xử lý hình ảnh
                    image_files = [os.path.join(PHOTO_DIR, f) for f in os.listdir(PHOTO_DIR) 
                                  if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                    if image_files:
                        latest_image = max(image_files, key=os.path.getctime)
                        print(f"📤 Đang gửi ảnh: {os.path.basename(latest_image)}...")
                        await send_image_data(websocket, latest_image, quality)
                    else:
                        print(f"❌ Không tìm thấy file ảnh nào")
                    
                    if not audio_files and not image_files:
                        print(f"❌ Không tìm thấy bất kỳ file nào")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Không có file nào",
                            "timestamp": datetime.datetime.now().isoformat()
                        }))
                else:
                    print(f"❓ Không nhận dạng được hành động: {action}")
                
                print(f"----- KẾT THÚC YÊU CẦU -----\n")
                
            except json.JSONDecodeError:
                logger.warning(f"Nhận được tin nhắn không phải JSON từ {client_info}")
                print(f"⚠️ Nhận được tin nhắn không phải JSON từ {client_info}")
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Tin nhắn phải ở định dạng JSON",
                    "timestamp": datetime.datetime.now().isoformat()
                }))
            except Exception as e:
                logger.error(f"Lỗi xử lý tin nhắn từ {client_info}: {e}")
                print(f"❌ Lỗi xử lý tin nhắn từ {client_info}: {e}")
                break
                
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client đã ngắt kết nối: {client_info}")
        print(f"\n===== NGẮT KẾT NỐI =====")
        print(f"🔌 Client {client_info} đã ngắt kết nối")
        print(f"⌚ Thời gian: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"========================\n")
    except Exception as e:
        logger.error(f"Lỗi xử lý client {client_info}: {e}")
        print(f"❌ Lỗi xử lý client {client_info}: {e}")
    finally:
        # Loại bỏ client khỏi danh sách kết nối
        connected_clients.remove(websocket)

async def broadcast_audio(audio_file_path):
    """Phát sóng dữ liệu âm thanh tới tất cả các client đang kết nối"""
    if not connected_clients:
        logger.info("Không có client nào đang kết nối để gửi âm thanh")
        return
    
    # Mã hóa file âm thanh thành base64
    try:
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
            base64_audio = base64.b64encode(audio_data).decode('utf-8')
        
        # Tạo timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Tạo tên file
        file_name = os.path.basename(audio_file_path)
        
        # Đóng gói message
        message = {
            "type": "audio",
            "data": base64_audio,
            "timestamp": timestamp,
            "device_name": DEVICE_NAME,
            "file_name": file_name
        }
        
        # Chuyển message thành JSON string
        json_message = json.dumps(message)
        
        # Gửi tới tất cả clients
        disconnected_clients = set()
        
        for websocket in connected_clients:
            try:
                await websocket.send(json_message)
            except websockets.exceptions.ConnectionClosed:
                # Đánh dấu client đã ngắt kết nối để loại bỏ sau
                disconnected_clients.add(websocket)
            except Exception as e:
                logger.error(f"Lỗi khi gửi tới client: {e}")
                disconnected_clients.add(websocket)
        
        # Loại bỏ các client đã ngắt kết nối
        for client in disconnected_clients:
            connected_clients.remove(client)
            
        logger.info(f"Đã phát sóng âm thanh {file_name} tới {len(connected_clients)} client")
    except Exception as e:
        logger.error(f"Lỗi khi phát sóng âm thanh {audio_file_path}: {e}")

async def broadcast_image(image_file_path):
    """Phát sóng dữ liệu hình ảnh tới tất cả các client đang kết nối"""
    if not connected_clients:
        logger.info("Không có client nào đang kết nối để gửi hình ảnh")
        return
    
    # Mã hóa file hình ảnh thành base64
    try:
        with open(image_file_path, "rb") as image_file:
            image_data = image_file.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Tạo timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Tạo tên file
        file_name = os.path.basename(image_file_path)
        
        # Đóng gói message
        message = {
            "type": "image",
            "data": base64_image,
            "timestamp": timestamp,
            "device_name": DEVICE_NAME,
            "file_name": file_name
        }
        
        # Chuyển message thành JSON string
        json_message = json.dumps(message)
        
        # Gửi tới tất cả clients
        disconnected_clients = set()
        
        for websocket in connected_clients:
            try:
                await websocket.send(json_message)
            except websockets.exceptions.ConnectionClosed:
                # Đánh dấu client đã ngắt kết nối để loại bỏ sau
                disconnected_clients.add(websocket)
            except Exception as e:
                logger.error(f"Lỗi khi gửi tới client: {e}")
                disconnected_clients.add(websocket)
        
        # Loại bỏ các client đã ngắt kết nối
        for client in disconnected_clients:
            connected_clients.remove(client)
            
        logger.info(f"Đã phát sóng hình ảnh {file_name} tới {len(connected_clients)} client")
    except Exception as e:
        logger.error(f"Lỗi khi phát sóng hình ảnh {image_file_path}: {e}")

async def monitor_files():
    """Theo dõi các thư mục để phát hiện file mới và phát sóng"""
    last_audio_time = 0
    last_image_time = 0
    
    while True:
        try:
            # Kiểm tra file âm thanh mới
            audio_files = [os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) 
                           if f.endswith('.mp3') or f.endswith('.wav')]
            if audio_files:
                latest_audio = max(audio_files, key=os.path.getctime)
                file_mtime = os.path.getmtime(latest_audio)
                
                if file_mtime > last_audio_time:
                    logger.info(f"Phát hiện file âm thanh mới: {os.path.basename(latest_audio)}")
                    await broadcast_audio(latest_audio)
                    last_audio_time = file_mtime
            
            # Kiểm tra file hình ảnh mới
            image_files = [os.path.join(PHOTO_DIR, f) for f in os.listdir(PHOTO_DIR) 
                           if f.endswith('.jpg') or f.endswith('.png')]
            if image_files:
                latest_image = max(image_files, key=os.path.getctime)
                file_mtime = os.path.getmtime(latest_image)
                
                if file_mtime > last_image_time:
                    logger.info(f"Phát hiện file hình ảnh mới: {os.path.basename(latest_image)}")
                    await broadcast_image(latest_image)
                    last_image_time = file_mtime
            
            # Chờ một lát trước khi kiểm tra lại
            await asyncio.sleep(1)  # Check every second
        except Exception as e:
            logger.error(f"Lỗi trong quá trình monitor: {e}")
            await asyncio.sleep(5)  # Wait longer after an error

async def start_server(host='0.0.0.0', port=WEBSOCKET_PORT):
    """Khởi động WebSocket server"""
    # Tạo các thư mục lưu trữ nếu chưa tồn tại
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)
    
    # Khởi động server với handle_client trực tiếp
    server = await websockets.serve(handle_client, host, port)
    logger.info(f"WebSocket server đang chạy tại ws://{host}:{port}")
    
    # Khởi động monitor để theo dõi file mới
    asyncio.create_task(monitor_files())
    
    # Giữ server chạy
    await server.wait_closed()

def run_websocket_server(host='0.0.0.0', port=WEBSOCKET_PORT):
    """Hàm chính để khởi động server từ bên ngoài"""
    try:
        asyncio.run(start_server(host, port))
    except KeyboardInterrupt:
        logger.info("WebSocket server đã dừng bởi người dùng")
    except Exception as e:
        logger.error(f"Lỗi khi khởi động WebSocket server: {e}")

# Hàm để chạy WebSocket server trong một thread riêng biệt
def start_websocket_server_in_thread():
    """Chạy WebSocket server trong một thread riêng biệt"""
    websocket_thread = threading.Thread(target=run_websocket_server)
    websocket_thread.daemon = True
    websocket_thread.start()
    return websocket_thread

if __name__ == "__main__":
    # Khởi động server khi chạy file này trực tiếp
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("WebSocket server đã dừng bởi người dùng")
    except Exception as e:
        logger.error(f"Lỗi khi khởi động server: {e}")