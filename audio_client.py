# File: audio_client.py
# Module xử lý kết nối và nhận âm thanh từ server

import os
import json
import base64
import asyncio
import threading
import time
import wave
import pyaudio
import websockets
import requests
import logging
from io import BytesIO
import numpy as np
from config import *

# Cấu hình logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('audio_client')

class AudioClient:
    """
    Client kết nối với Raspberry Pi server để nhận và phát âm thanh
    """
    def __init__(self):
        # Khởi tạo các biến
        self.websocket = None
        self.connected = False
        self.ws_thread = None
        self.running = False
        self.audio_player = None
        self.last_audio_data = None
        self.last_audio_time = None
        self.callback_new_audio = None  # Callback khi có âm thanh mới
        self.callback_connection_change = None  # Callback khi trạng thái kết nối thay đổi
        
        # Tạo thư mục lưu âm thanh nếu chưa tồn tại
        os.makedirs(AUDIO_DIR, exist_ok=True)
        
        # Khởi tạo PyAudio để phát âm thanh
        try:
            self.pyaudio = pyaudio.PyAudio()
            self.audio_available = True
            logger.info("PyAudio đã được khởi tạo thành công")
        except Exception as e:
            logger.error(f"Không thể khởi tạo PyAudio: {e}")
            self.pyaudio = None
            self.audio_available = False
            
    def set_callback_new_audio(self, callback):
        """
        Đặt callback khi có âm thanh mới
        
        Args:
            callback: Hàm callback(audio_path, is_crying)
        """
        self.callback_new_audio = callback
        
    def set_callback_connection_change(self, callback):
        """
        Đặt callback khi trạng thái kết nối thay đổi
        
        Args:
            callback: Hàm callback(connected)
        """
        self.callback_connection_change = callback
        
    def start(self):
        """
        Bắt đầu kết nối đến server
        """
        if self.running:
            return
            
        self.running = True
        
        # Khởi chạy WebSocket client trong một thread riêng
        self.ws_thread = threading.Thread(target=self._run_websocket_client)
        self.ws_thread.daemon = True
        self.ws_thread.start()
        
        logger.info("Đã khởi động AudioClient")
        
    def _run_websocket_client(self):
        """
        Chạy WebSocket client trong một event loop riêng
        """
        # Tạo event loop mới cho thread này
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Chạy WebSocket client
        while self.running:
            try:
                loop.run_until_complete(self._connect_websocket())
            except Exception as e:
                logger.error(f"Lỗi WebSocket: {e}")
                
            # Đợi trước khi thử kết nối lại
            if self.running:
                logger.info("Thử kết nối lại trong 5 giây...")
                time.sleep(5)
                
        logger.info("WebSocket client đã dừng")
        
    async def _connect_websocket(self):
        """
        Kết nối đến WebSocket server và xử lý các thông điệp
        """
        ws_url = f"ws://{SERVER_HOST}:{WEBSOCKET_PORT}"
        logger.info(f"Đang kết nối đến WebSocket server: {ws_url}")
        
        try:
            async with websockets.connect(ws_url) as websocket:
                self.websocket = websocket
                self.connected = True
                
                # Gọi callback thông báo kết nối thành công
                if self.callback_connection_change:
                    self.callback_connection_change(True)
                
                logger.info("Đã kết nối đến WebSocket server")
                
                # Gửi thông điệp đăng ký nhận thông báo âm thanh
                register_msg = {
                    "type": "register",
                    "client_type": "audio_client"
                }
                await websocket.send(json.dumps(register_msg))
                
                # Vòng lặp nhận thông điệp
                while self.running:
                    try:
                        message = await websocket.recv()
                        await self._process_message(message)
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Kết nối WebSocket bị đóng")
                        break
                    except Exception as e:
                        logger.error(f"Lỗi khi xử lý thông điệp: {e}")
                        
        except Exception as e:
            logger.error(f"Không thể kết nối đến WebSocket server: {e}")
            
        # Cập nhật trạng thái kết nối
        self.websocket = None
        self.connected = False
        
        # Gọi callback thông báo mất kết nối
        if self.callback_connection_change:
            self.callback_connection_change(False)
            
    async def _process_message(self, message):
        """
        Xử lý thông điệp nhận được từ WebSocket server
        
        Args:
            message: Thông điệp nhận được
        """
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            if message_type == 'audio_update':
                # Thông điệp cập nhật âm thanh mới
                is_crying = data.get('is_crying', False)
                timestamp = data.get('timestamp', '')
                
                if is_crying:
                    logger.warning(f"⚠️ Phát hiện tiếng khóc của em bé! (Timestamp: {timestamp})")
                    
                    # Tải âm thanh từ server
                    await self._download_latest_audio(is_crying)
                    
            elif message_type == 'ping':
                # Thông điệp ping để giữ kết nối
                await self.websocket.send(json.dumps({'type': 'pong'}))
                
            else:
                logger.debug(f"Nhận thông điệp không xác định: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("Nhận thông điệp không hợp lệ")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý thông điệp: {e}")
            
    async def _download_latest_audio(self, is_crying=False):
        """
        Tải file âm thanh mới nhất từ server HTTP
        
        Args:
            is_crying: Có phải là tiếng khóc không
        """
        audio_url = f"http://{SERVER_HOST}:{HTTP_PORT}/api/audio/latest"
        
        try:
            # Tải âm thanh không đồng bộ để không chặn luồng xử lý WebSocket
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.get(audio_url, timeout=10)
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Kiểm tra dữ liệu phản hồi
                if 'data' in data and data['status'] == 'success':
                    # Lấy dữ liệu âm thanh và giải mã base64
                    audio_data = data['data'].get('audio_data')
                    timestamp = data['data'].get('timestamp', '')
                    is_crying = data['data'].get('is_crying', False)
                    
                    if audio_data:
                        # Lưu file âm thanh
                        audio_bytes = base64.b64decode(audio_data)
                        filename = f"audio_{timestamp.replace(':', '-').replace(' ', '_')}.wav"
                        filepath = os.path.join(AUDIO_DIR, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(audio_bytes)
                            
                        logger.info(f"Đã tải âm thanh: {filename}")
                        
                        # Cập nhật biến lưu trạng thái
                        self.last_audio_time = timestamp
                        self.last_audio_data = audio_bytes
                        
                        # Phát âm thanh tự động nếu là tiếng khóc
                        if is_crying:
                            self.play_audio(audio_bytes)
                            
                        # Gọi callback nếu có
                        if self.callback_new_audio:
                            self.callback_new_audio(filepath, is_crying)
                            
                        return filepath
                    else:
                        logger.warning("Không có dữ liệu âm thanh trong phản hồi")
                else:
                    logger.warning(f"Phản hồi không hợp lệ từ server: {data}")
            else:
                logger.error(f"Không thể tải âm thanh, mã lỗi: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Lỗi khi tải âm thanh: {e}")
            
        return None
        
    def play_audio(self, audio_data=None, audio_file=None):
        """
        Phát âm thanh từ dữ liệu hoặc file
        
        Args:
            audio_data: Dữ liệu âm thanh dạng bytes
            audio_file: Đường dẫn đến file âm thanh
            
        Returns:
            bool: True nếu phát âm thanh thành công, False nếu thất bại
        """
        if not self.audio_available:
            logger.warning("PyAudio không khả dụng, không thể phát âm thanh")
            return False
            
        # Nếu đang phát, dừng playback hiện tại
        self.stop_audio()
        
        try:
            # Ưu tiên dùng audio_data nếu có
            if audio_data is None and audio_file is not None:
                with open(audio_file, 'rb') as f:
                    audio_data = f.read()
                    
            if audio_data is None:
                logger.warning("Không có dữ liệu âm thanh để phát")
                return False
                
            # Đọc từ bytes thành WAV
            wave_file = wave.open(BytesIO(audio_data), 'rb')
            
            # Lấy các tham số
            channels = wave_file.getnchannels()
            sample_width = wave_file.getsampwidth()
            framerate = wave_file.getframerate()
            frames = wave_file.readframes(wave_file.getnframes())
            
            # Khởi tạo audio stream
            self.audio_player = self.pyaudio.open(
                format=self.pyaudio.get_format_from_width(sample_width),
                channels=channels,
                rate=framerate,
                output=True
            )
            
            # Phát âm thanh trong một thread riêng
            playback_thread = threading.Thread(
                target=self._playback_thread,
                args=(frames, self.audio_player)
            )
            playback_thread.daemon = True
            playback_thread.start()
            
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi phát âm thanh: {e}")
            return False
            
    def _playback_thread(self, frames, stream):
        """
        Thread phát âm thanh
        
        Args:
            frames: Dữ liệu âm thanh
            stream: Stream đầu ra
        """
        try:
            # Phát âm thanh
            stream.write(frames)
            
            # Đóng stream khi phát xong
            stream.stop_stream()
            stream.close()
            self.audio_player = None
            
        except Exception as e:
            logger.error(f"Lỗi trong quá trình phát: {e}")
            if stream:
                stream.close()
            self.audio_player = None
            
    def stop_audio(self):
        """
        Dừng phát âm thanh
        """
        if self.audio_player and self.audio_player.is_active():
            self.audio_player.stop_stream()
            self.audio_player.close()
            self.audio_player = None
            
    def get_latest_audio_info(self):
        """
        Lấy thông tin về âm thanh mới nhất
        
        Returns:
            dict: Thông tin âm thanh mới nhất hoặc None
        """
        if self.last_audio_time:
            return {
                'timestamp': self.last_audio_time,
                'has_data': self.last_audio_data is not None
            }
        return None
        
    def stop(self):
        """
        Dừng client
        """
        self.running = False
        self.stop_audio()
        
        if self.ws_thread:
            self.ws_thread.join(timeout=2.0)
            
        if self.pyaudio:
            self.pyaudio.terminate()
            
        logger.info("Đã dừng AudioClient")
        
    def __del__(self):
        """
        Hủy đối tượng
        """
        self.stop()


# Hàm test module
if __name__ == "__main__":
    print("Test AudioClient")
    
    client = AudioClient()
    
    def on_new_audio(audio_path, is_crying):
        print(f"Nhận được âm thanh mới: {audio_path}")
        print(f"Tiếng khóc: {'Có' if is_crying else 'Không'}")
        
    def on_connection_change(connected):
        print(f"Trạng thái kết nối: {'Đã kết nối' if connected else 'Mất kết nối'}")
        
    client.set_callback_new_audio(on_new_audio)
    client.set_callback_connection_change(on_connection_change)
    
    client.start()
    
    try:
        # Chạy trong 60 giây
        print("Chạy trong 60 giây, Ctrl+C để dừng...")
        for _ in range(60):
            time.sleep(1)
    except KeyboardInterrupt:
        print("Dừng chương trình...")
        
    client.stop()
    print("Đã dừng client")