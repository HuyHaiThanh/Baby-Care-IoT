# File: photo_client.py
# Client để nhận dữ liệu ảnh từ Raspberry Pi qua WebSocket

import asyncio
import websockets
import json
import base64
import os
import datetime
import logging
import time
from PIL import Image
import io
from config import WEBSOCKET_URL, DOWNLOAD_DIR, CLIENT_NAME

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('photo_client')

class PhotoClient:
    def __init__(self, on_image_received=None):
        """
        Khởi tạo client photo
        
        Args:
            on_image_received: Callback được gọi khi nhận được ảnh mới
        """
        self.websocket = None
        self.connected = False
        self.on_image_received = on_image_received
        self.latest_image_path = None
        self.latest_image_data = None
        self.reconnect_delay = 5  # Thời gian chờ trước khi kết nối lại (giây)

    async def connect(self):
        """Kết nối tới WebSocket server"""
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            
            # Kết nối tới server
            self.websocket = await websockets.connect(WEBSOCKET_URL)
            self.connected = True
            logger.info(f"Đã kết nối tới server: {WEBSOCKET_URL}")
            
            # Gửi tin nhắn xác thực
            await self._send_auth_message()
            
            return True
        except Exception as e:
            logger.error(f"Lỗi kết nối tới server: {e}")
            self.connected = False
            return False

    async def _send_auth_message(self):
        """Gửi thông tin xác thực tới server"""
        auth_message = {
            "type": "auth",
            "client_name": CLIENT_NAME,
            "client_type": "photo",
            "timestamp": datetime.datetime.now().isoformat()
        }
        await self.websocket.send(json.dumps(auth_message))

    async def request_latest_image(self, quality="high"):
        """
        Gửi yêu cầu lấy ảnh mới nhất từ server
        
        Args:
            quality: Chất lượng ảnh yêu cầu ("high", "medium", "low")
        """
        if not self.connected:
            logger.warning("Không thể gửi yêu cầu: Chưa kết nối tới server")
            return False
            
        try:
            # Tạo tin nhắn yêu cầu với nhiều tùy chọn
            request_message = {
                "action": "request_image",
                "timestamp": datetime.datetime.now().isoformat(),
                "quality": quality,  # Thêm tùy chọn chất lượng ảnh
                "paths": [
                    # Thêm nhiều đường dẫn có thể để server tìm
                    "/home/pi/Baby-Care-IoT/camera_data/photos",
                    "camera_data/photos",
                    "../camera_data/photos"
                ]
            }
            
            # Gửi yêu cầu với timeout
            await asyncio.wait_for(
                self.websocket.send(json.dumps(request_message)), 
                timeout=5.0
            )
            
            logger.info(f"Đã gửi yêu cầu lấy ảnh mới nhất (chất lượng: {quality})")
            return True
        except asyncio.TimeoutError:
            logger.error("Hết thời gian chờ khi gửi yêu cầu")
            return False
        except Exception as e:
            logger.error(f"Lỗi khi gửi yêu cầu: {e}")
            self.connected = False
            return False

    async def _save_image(self, base64_data, file_name=None):
        """
        Lưu ảnh từ dữ liệu base64
        
        Args:
            base64_data: Dữ liệu ảnh đã mã hóa base64
            file_name: Tên file (nếu None sẽ tạo tự động)
            
        Returns:
            str: Đường dẫn đến file đã lưu
        """
        try:
            # Giải mã dữ liệu
            image_data = base64.b64decode(base64_data)
            
            # Tạo tên file nếu chưa có
            if not file_name:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"image_{timestamp}.jpg"
            
            # Đường dẫn đầy đủ
            file_path = os.path.join(DOWNLOAD_DIR, file_name)
            
            # Ghi dữ liệu
            with open(file_path, "wb") as f:
                f.write(image_data)
                
            logger.info(f"Đã lưu ảnh: {file_path}")
            
            # Lưu thông tin ảnh mới nhất
            self.latest_image_path = file_path
            self.latest_image_data = image_data
            
            # Gọi callback nếu có
            if self.on_image_received:
                try:
                    # Tạo đối tượng PIL Image
                    image = Image.open(io.BytesIO(image_data))
                    # Gọi callback với đường dẫn và đối tượng ảnh
                    self.on_image_received(file_path, image)
                except Exception as callback_error:
                    logger.error(f"Lỗi trong callback on_image_received: {callback_error}")
                    
            return file_path
        except Exception as e:
            logger.error(f"Lỗi khi lưu ảnh: {e}")
            return None

    async def listen(self):
        """Lắng nghe và xử lý tin nhắn từ server"""
        if not self.connected:
            logger.warning("Không thể lắng nghe: Chưa kết nối tới server")
            return
            
        try:
            while True:
                # Nhận tin nhắn từ server với timeout
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("Không nhận được phản hồi từ server trong 30 giây, kiểm tra kết nối...")
                    # Gửi ping để kiểm tra kết nối
                    try:
                        pong_waiter = await self.websocket.ping()
                        await asyncio.wait_for(pong_waiter, timeout=5.0)
                        logger.info("Server vẫn hoạt động, tiếp tục lắng nghe...")
                        continue
                    except:
                        logger.error("Server không phản hồi ping, kết nối có thể đã mất")
                        self.connected = False
                        break
                
                try:
                    # Đo thời gian xử lý để phát hiện vấn đề hiệu suất
                    start_time = time.time()
                    
                    # Giải mã JSON
                    data = json.loads(message)
                    
                    # Xử lý các loại tin nhắn
                    if data.get("type") == "image":
                        # Nhận được dữ liệu ảnh
                        file_name = data.get('file_name', 'unknown')
                        logger.info(f"Nhận được ảnh: {file_name} - Kích thước dữ liệu: {len(message) // 1024} KB")
                        
                        # Lưu ảnh trong task riêng biệt để không chặn luồng chính
                        asyncio.create_task(self._save_image(data.get("data"), file_name))
                        
                        # Báo cáo thời gian xử lý
                        process_time = time.time() - start_time
                        if process_time > 1.0:
                            logger.warning(f"Xử lý ảnh mất nhiều thời gian: {process_time:.2f} giây")
                    
                    elif data.get("type") == "connection":
                        # Thông báo kết nối
                        logger.info(f"Kết nối: {data.get('message', '')}")
                    
                    elif data.get("type") == "error":
                        # Thông báo lỗi
                        error_msg = data.get('message', '')
                        logger.error(f"Server báo lỗi: {error_msg}")
                        
                        # Nếu không có file ảnh, thử gửi lại yêu cầu với các đường dẫn thay thế
                        if "Không có file hình ảnh" in error_msg:
                            logger.info("Thử gửi lại yêu cầu với tùy chọn khác...")
                            # Thử với chất lượng medium rồi low nếu không có ảnh
                            await self.request_latest_image(quality="medium")
                
                except json.JSONDecodeError:
                    logger.warning(f"Nhận được tin nhắn không phải JSON")
                except Exception as e:
                    logger.error(f"Lỗi xử lý tin nhắn: {e}")
                
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Kết nối WebSocket bị đóng: {e}")
            self.connected = False
        except Exception as e:
            logger.error(f"Lỗi khi lắng nghe tin nhắn: {e}")
            self.connected = False

    async def run(self):
        """Chạy client và tự động kết nối lại nếu mất kết nối"""
        retry_count = 0
        max_retries = 5
        current_quality = "high"  # Bắt đầu với chất lượng cao
        
        while True:
            if not self.connected:
                # Tăng số lần thử kết nối
                retry_count += 1
                
                # Thử kết nối lại
                logger.info(f"Đang kết nối tới server... (lần thử {retry_count}/{max_retries})")
                connected = await self.connect()
                
                if not connected:
                    # Nếu không kết nối được và đã thử đủ số lần, tăng thời gian chờ
                    if retry_count >= max_retries:
                        logger.warning(f"Không thể kết nối sau {max_retries} lần thử. Tăng thời gian chờ.")
                        await asyncio.sleep(self.reconnect_delay * 2)
                        retry_count = 0  # Reset số lần thử
                    else:
                        # Nếu chưa đủ số lần thử, đợi một lúc trước khi thử lại
                        logger.info(f"Kết nối thất bại. Thử lại sau {self.reconnect_delay} giây...")
                        await asyncio.sleep(self.reconnect_delay)
                    continue
                
                # Reset số lần thử khi kết nối thành công
                retry_count = 0
                
                # Khi đã kết nối, gửi yêu cầu lấy ảnh mới nhất với chất lượng hiện tại
                logger.info(f"Gửi yêu cầu ảnh với chất lượng: {current_quality}")
                request_success = await self.request_latest_image(quality=current_quality)
                
                # Nếu không gửi được yêu cầu, thử lại với chất lượng thấp hơn
                if not request_success and current_quality == "high":
                    logger.info("Thử lại với chất lượng trung bình...")
                    current_quality = "medium"
                    await self.request_latest_image(quality=current_quality)
            
            try:
                # Bắt đầu lắng nghe tin nhắn
                await self.listen()
            except Exception as e:
                logger.error(f"Lỗi trong quá trình lắng nghe: {e}")
            
            # Nếu đến đây, tức là đã mất kết nối
            self.connected = False
            
            # Giảm chất lượng ảnh nếu gặp vấn đề kết nối
            if current_quality == "high":
                current_quality = "medium"
                logger.info("Chuyển sang chất lượng ảnh trung bình do kết nối không ổn định")
            elif current_quality == "medium":
                current_quality = "low"
                logger.info("Chuyển sang chất lượng ảnh thấp do kết nối không ổn định")
            
            logger.info(f"Mất kết nối. Thử kết nối lại sau {self.reconnect_delay} giây...")
            await asyncio.sleep(self.reconnect_delay)

    def get_latest_image(self):
        """Trả về đường dẫn đến ảnh mới nhất đã lưu"""
        return self.latest_image_path
        
    async def close(self):
        """Đóng kết nối"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info("Đã đóng kết nối")

def start_client(websocket_url=None):
    """
    Khởi động client trong một thread riêng biệt
    
    Args:
        websocket_url: URL WebSocket tùy chọn để ghi đè lên giá trị từ config
    """
    import threading
    import nest_asyncio
    from config import WEBSOCKET_URL as CONFIG_WEBSOCKET_URL
    
    # Cho phép lồng event loop asyncio
    nest_asyncio.apply()
    
    # Tạo event loop mới
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Khởi tạo client
    client = PhotoClient()
    
    # Hàm chạy client trong thread riêng
    def run_client():
        global WEBSOCKET_URL
        # Sử dụng URL được cung cấp nếu có
        if websocket_url:
            WEBSOCKET_URL = websocket_url
            logger.info(f"Sử dụng WebSocket URL tùy chỉnh: {websocket_url}")
        loop.run_until_complete(client.run())
    
    # Tạo và chạy thread
    client_thread = threading.Thread(target=run_client)
    client_thread.daemon = True
    client_thread.start()
    
    return client

# Test nếu chạy trực tiếp
if __name__ == "__main__":
    async def main():
        # Hàm callback khi nhận được ảnh mới
        def on_image_received(image_path, image):
            print(f"Đã nhận và lưu ảnh mới: {image_path}")
            print(f"Kích thước ảnh: {image.size}")
            
        # Khởi tạo client với callback
        client = PhotoClient(on_image_received=on_image_received)
        
        # Kết nối tới server
        connected = await client.connect()
        
        if connected:
            # Gửi yêu cầu lấy ảnh mới nhất
            await client.request_latest_image()
            
            # Lắng nghe tin nhắn từ server
            await client.listen()
        else:
            print("Không thể kết nối tới server, vui lòng kiểm tra lại cấu hình")
    
    # Chạy client
    asyncio.run(main())