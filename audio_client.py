# File: audio_client.py
# Module xử lý ghi âm và gửi dữ liệu âm thanh đến server

import os
import time
import datetime
import threading
import wave
import numpy as np
import queue
import json
import base64
import websocket
import requests
import scipy.signal as signal
from scipy.fft import fft, fftfreq
from io import BytesIO
from config import (
    AUDIO_DIR, TEMP_DIR, DEVICE_ID, AUDIO_API_ENDPOINT, 
    AUDIO_WS_ENDPOINT, SAMPLE_RATE, CHANNELS, 
    AUDIO_DURATION, AUDIO_SLIDE_SIZE, RECONNECT_INTERVAL
)
from utils import get_timestamp, make_api_request, logger

# Cấu hình cho hệ thống phát hiện tiếng khóc
FREQ_MIN = 250  # Tần số thấp nhất (Hz)
FREQ_MAX = 750  # Tần số cao nhất (Hz)
ENERGY_THRESHOLD = 0.01  # Ngưỡng năng lượng để phát hiện âm thanh
VAD_THRESHOLD = 0.15  # Ngưỡng VAD
TARGET_FREQ_THRESHOLD = 30.0  # Ngưỡng % năng lượng trong dải tần số quan tâm

# Flag for checking if PyAudio is available
PYAUDIO_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
    logger.info("Đã phát hiện PyAudio.")
except ImportError:
    logger.warning("CẢNH BÁO: Không tìm thấy thư viện PyAudio. Sẽ chỉ tạo file âm thanh giả lập.")

class AudioClient:
    """
    Client xử lý ghi âm và gửi dữ liệu âm thanh đến server
    """
    def __init__(self, use_websocket=True, use_vad_filter=True):
        """
        Khởi tạo audio client
        
        Args:
            use_websocket (bool): Sử dụng WebSocket cho kết nối thời gian thực
            use_vad_filter (bool): Áp dụng lọc VAD và tần số
        """
        self.use_websocket = use_websocket
        self.use_vad_filter = use_vad_filter
        self.running = False
        self.ws = None
        self.ws_connected = False
        self.ws_thread = None
        self.audio = None
        self.stream = None
        self.is_recording = False
        self.processing_thread = None
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.chunk_size = 1024
        self.format = None
        
        # Bộ đếm gửi dữ liệu
        self.sent_success_count = 0
        self.sent_fail_count = 0
        self.total_audio_processed = 0
        
        # Theo dõi file đang xử lý
        self.current_audio_file = "Không có"
        self.processing_status = "Đang chờ"
        
        if PYAUDIO_AVAILABLE:
            self.format = pyaudio.paInt16
            self.audio = pyaudio.PyAudio()
        
        self.sample_rate = SAMPLE_RATE
        self.channels = CHANNELS
        self.window_size = AUDIO_DURATION
        self.slide_size = AUDIO_SLIDE_SIZE
        self.frames_per_window = int(self.sample_rate * self.window_size)
        self.frames_per_slide = int(self.sample_rate * self.slide_size)
        
        # Tạo các thư mục cần thiết
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        
    def start(self):
        """
        Khởi động audio client
        """
        self.running = True
        
        # Khởi động kết nối WebSocket nếu cần
        if self.use_websocket:
            self.ws_thread = threading.Thread(target=self._websocket_thread)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
        # Khởi động ghi âm
        if PYAUDIO_AVAILABLE:
            self.start_recording()
            
        logger.info("Audio client đã khởi động")
        return True
        
    def stop(self):
        """
        Dừng audio client
        """
        self.running = False
        
        # Dừng ghi âm
        self.stop_recording()
        
        # Đóng kết nối WebSocket nếu có
        if self.ws and self.ws_connected:
            self.ws.close()
            self.ws_connected = False
            
        # Giải phóng tài nguyên PyAudio
        if self.audio:
            self.audio.terminate()
            self.audio = None
            
        logger.info("Audio client đã dừng")
        
    def _websocket_thread(self):
        """
        Thread xử lý kết nối WebSocket
        """
        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'prediction':
                    # Server gửi về kết quả dự đoán
                    predicted_class = data.get('predicted_class', '')
                    confidence = data.get('confidence', 0)
                    logger.info(f"Nhận kết quả dự đoán: {predicted_class} (độ tin cậy: {confidence:.2f})")
                
                elif msg_type == 'alert':
                    # Server gửi cảnh báo
                    msg = data.get('message', '')
                    confidence = data.get('confidence', 0)
                    is_consecutive = data.get('consecutive', False)
                    logger.warning(f"⚠️ CẢNH BÁO: {msg} (độ tin cậy: {confidence:.2f})")
                    if is_consecutive:
                        logger.warning("⚠️ PHÁT HIỆN LIÊN TIẾP - CÓ THỂ LÀ TIẾNG KHÓC CỦA EM BÉ!")
                        
                elif msg_type == 'error':
                    # Thông báo lỗi
                    msg = data.get('message', '')
                    details = data.get('details', '')
                    logger.error(f"Lỗi từ server âm thanh: {msg}")
                    if details:
                        logger.error(f"Chi tiết: {details}")
            
            except json.JSONDecodeError:
                logger.error(f"Không thể giải mã thông điệp WebSocket: {message}")
            except Exception as e:
                logger.error(f"Lỗi khi xử lý thông điệp WebSocket: {e}")

        def on_error(ws, error):
            logger.error(f"Lỗi WebSocket âm thanh: {error}")
            self.ws_connected = False

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"WebSocket âm thanh đã đóng: {close_status_code} - {close_msg}")
            self.ws_connected = False
            
            # Thử kết nối lại sau một khoảng thời gian nếu client vẫn đang chạy
            if self.running:
                logger.info(f"Đang thử kết nối lại WebSocket âm thanh sau {RECONNECT_INTERVAL} giây...")
                time.sleep(RECONNECT_INTERVAL)
                self._connect_websocket()

        def on_open(ws):
            logger.info("Đã kết nối WebSocket tới server xử lý âm thanh")
            self.ws_connected = True
            
            # Gửi thông tin thiết bị
            self.ws.send(json.dumps({
                'type': 'connect',
                'client_id': DEVICE_ID,
                'timestamp': time.time()
            }))
        
        # Khởi tạo và kết nối WebSocket
        def _connect_websocket():
            try:
                if hasattr(self, 'ws') and self.ws:
                    self.ws.close()
                    
                logger.info(f"Đang kết nối tới {AUDIO_WS_ENDPOINT}/{DEVICE_ID}")
                self.ws = websocket.WebSocketApp(
                    f"{AUDIO_WS_ENDPOINT}/{DEVICE_ID}",
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Lỗi kết nối WebSocket âm thanh: {e}")
                self.ws_connected = False
                time.sleep(RECONNECT_INTERVAL)  # Đợi trước khi thử lại
        
        self._connect_websocket = _connect_websocket
        
        # Vòng lặp kết nối lại nếu mất kết nối
        while self.running:
            if not self.ws_connected:
                _connect_websocket()
            time.sleep(1)

    def start_recording(self):
        """
        Bắt đầu ghi âm từ microphone.
        Tạo một thread mới để xử lý âm thanh theo sliding window.
        """
        if not PYAUDIO_AVAILABLE or self.is_recording:
            return False
            
        self.is_recording = True
        self.audio_buffer = []
        
        def callback(in_data, frame_count, time_info, status):
            """
            Hàm callback cho PyAudio, nhận dữ liệu âm thanh từ microphone.
            """
            self.audio_buffer.append(np.frombuffer(in_data, dtype=np.int16))
            return (in_data, pyaudio.paContinue)
            
        try:
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=callback
            )
            
            # Khởi động thread xử lý âm thanh theo sliding window
            self.processing_thread = threading.Thread(target=self._process_audio)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            logger.info("Đã bắt đầu ghi âm với chế độ sliding window")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu ghi âm: {e}")
            self.is_recording = False
            return False
    
    def stop_recording(self):
        """
        Dừng ghi âm và đóng audio stream.
        """
        if not self.is_recording:
            return
            
        self.is_recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        # Đợi thread xử lý kết thúc nếu nó tồn tại
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)  # Đợi tối đa 1 giây
        
        logger.info("Đã dừng ghi âm")
    
    def voice_activity_detection(self, audio_data, frame_duration=0.03, threshold=VAD_THRESHOLD):
        """
        Phát hiện các đoạn có hoạt động âm thanh (VAD)
        
        Args:
            audio_data: Dữ liệu âm thanh
            frame_duration: Độ dài mỗi khung (giây)
            threshold: Ngưỡng năng lượng để xác định có hoạt động âm thanh
            
        Returns:
            tuple: (có_hoạt_động, tỷ_lệ_khung_hoạt_động)
        """
        # Chuẩn hóa âm thanh để tính toán
        normalized_data = audio_data.astype(np.float32) / (np.max(np.abs(audio_data)) + 1e-10)
        
        # Tính kích thước khung
        frame_size = int(self.sample_rate * frame_duration)
        num_frames = int(np.ceil(len(normalized_data) / frame_size))
        
        # Tạo mảng lưu mức năng lượng từng khung
        frame_energy = np.zeros(num_frames)
        
        # Tính năng lượng cho từng khung
        for i in range(num_frames):
            start = i * frame_size
            end = min(start + frame_size, len(normalized_data))
            frame = normalized_data[start:end]
            frame_energy[i] = np.mean(frame**2)
        
        # Áp dụng ngưỡng để xác định các khung có hoạt động âm thanh
        vad_mask = frame_energy > threshold
        vad_ratio = np.mean(vad_mask)
        
        # Có hoạt động âm thanh nếu tỷ lệ trên ngưỡng VAD
        has_activity = vad_ratio > 0.2  # Ít nhất 20% khung có hoạt động
        
        return has_activity, vad_ratio
    
    def frequency_analysis(self, audio_data, freq_min=FREQ_MIN, freq_max=FREQ_MAX):
        """
        Phân tích tần số và xác định phần trăm năng lượng âm thanh trong dải tần số quan tâm
        
        Args:
            audio_data: Dữ liệu âm thanh
            freq_min: Tần số thấp nhất quan tâm (Hz)
            freq_max: Tần số cao nhất quan tâm (Hz)
            
        Returns:
            float: Phần trăm năng lượng âm thanh trong dải tần số quan tâm
        """
        # Chuẩn hóa âm thanh
        normalized_data = audio_data.astype(np.float32) / (np.max(np.abs(audio_data)) + 1e-10)
        
        # Tính FFT
        n = len(normalized_data)
        yf = fft(normalized_data)
        xf = fftfreq(n, 1 / self.sample_rate)
        
        # Lấy nửa đầu của FFT (tần số dương)
        yf_abs = np.abs(yf[:n//2])
        xf = xf[:n//2]
        
        # Tổng năng lượng
        total_energy = np.sum(yf_abs**2)
        
        # Chỉ lọc trong dải tần số quan tâm
        mask = (xf >= freq_min) & (xf <= freq_max)
        target_energy = np.sum(yf_abs[mask]**2)
        
        # Tính phần trăm
        if total_energy > 0:
            percent = (target_energy / total_energy) * 100
        else:
            percent = 0
            
        return percent
    
    def should_send_audio(self, audio_data):
        """
        Kiểm tra xem đoạn âm thanh có nên được gửi đi không dựa trên VAD và phân tích tần số
        
        Args:
            audio_data: Dữ liệu âm thanh
            
        Returns:
            tuple: (nên_gửi, thông_tin_phân_tích)
        """
        if not self.use_vad_filter:
            return True, {"vad_filtered": False, "reason": "VAD filter is disabled"}
            
        # Kiểm tra năng lượng tổng thể
        energy = np.mean(np.abs(audio_data.astype(np.float32)))
        if energy < ENERGY_THRESHOLD:
            return False, {"vad_filtered": True, "reason": "Low energy", "energy": energy}
        
        # Kiểm tra VAD
        has_activity, vad_ratio = self.voice_activity_detection(audio_data)
        if not has_activity:
            return False, {"vad_filtered": True, "reason": "No voice activity", "vad_ratio": vad_ratio}
        
        # Phân tích tần số
        target_freq_energy = self.frequency_analysis(audio_data)
        if target_freq_energy < TARGET_FREQ_THRESHOLD:
            return False, {
                "vad_filtered": True, 
                "reason": "Low energy in target frequency range", 
                "target_freq_energy": target_freq_energy
            }
        
        # Nếu qua được tất cả các bộ lọc
        return True, {
            "vad_filtered": False,
            "has_activity": has_activity,
            "vad_ratio": vad_ratio,
            "target_freq_energy": target_freq_energy,
            "energy": energy
        }
        
    def _process_audio(self):
        """
        Xử lý âm thanh theo sliding window.
        
        Phương thức này liên tục theo dõi buffer âm thanh. Khi đủ dữ liệu cho một cửa sổ 
        (ví dụ: 3 giây), nó xử lý cửa sổ đó và sau đó trượt một khoảng slide_size 
        (ví dụ: 1 giây) để chuẩn bị cho cửa sổ tiếp theo.
        """
        frames_accumulated = 0
        buffer_ready = False  # Cờ để chỉ ra khi nào có đủ dữ liệu cho một cửa sổ đầy đủ
        
        while self.is_recording:
            if len(self.audio_buffer) > 0:
                with self.buffer_lock:
                    # Tính tổng số mẫu âm thanh đã tích lũy
                    total_samples_in_buffer = sum(len(chunk) for chunk in self.audio_buffer)
                    frames_accumulated = total_samples_in_buffer
                    
                    # Kiểm tra nếu đủ dữ liệu cho một cửa sổ
                    if not buffer_ready and frames_accumulated >= self.frames_per_window:
                        buffer_ready = True
                    
                    # Chỉ xử lý cửa sổ khi có đủ dữ liệu
                    if buffer_ready and frames_accumulated >= self.frames_per_window:
                        # Ghép tất cả các chunk thành một mảng duy nhất
                        flat_buffer = np.concatenate(self.audio_buffer)
                        
                        # Trích xuất cửa sổ cuối cùng (3 giây)
                        window_data = flat_buffer[-self.frames_per_window:]
                        
                        # Kiểm tra độ dài của cửa sổ trước khi xử lý
                        if len(window_data) == self.frames_per_window:
                            self.process_window(window_data)
                        else:
                            logger.warning("Không đủ dữ liệu cho một cửa sổ đầy đủ. Đang đợi thêm dữ liệu...")
                            continue
                        
                        # Xóa đúng số lượng khung âm thanh tương ứng với slide_size
                        # Điều này cho phép các cửa sổ chồng lấp lên nhau
                        samples_to_remove = self.frames_per_slide
                        while samples_to_remove > 0 and len(self.audio_buffer) > 0:
                            if len(self.audio_buffer[0]) <= samples_to_remove:
                                samples_to_remove -= len(self.audio_buffer[0])
                                self.audio_buffer.pop(0)
                            else:
                                self.audio_buffer[0] = self.audio_buffer[0][samples_to_remove:]
                                samples_to_remove = 0
                        
                        # Cập nhật frames_accumulated sau khi xóa
                        frames_accumulated = sum(len(chunk) for chunk in self.audio_buffer)
                        
            # Ngủ một chút để giảm tải cho CPU (quan trọng cho Raspberry Pi)
            time.sleep(0.2)
    
    def process_window(self, window_data):
        """
        Xử lý một cửa sổ dữ liệu âm thanh.
        
        Args:
            window_data (numpy.ndarray): Dữ liệu âm thanh cho cửa sổ hiện tại
        """
        string_timestamp, float_timestamp = get_timestamp()
        chunk_id = f"audio_{string_timestamp}"
        
        # Cập nhật trạng thái xử lý
        self.processing_status = "Đang phân tích âm thanh"
        
        # Đầu tiên kiểm tra xem đoạn âm thanh này có nên được gửi đi không
        should_send, analysis_info = self.should_send_audio(window_data)
        
        # Tăng biến đếm tổng số mẫu đã xử lý
        self.total_audio_processed += 1
        
        if should_send:
            logger.info(f"Phát hiện âm thanh quan trọng (năng lượng tần số 250-750Hz: {analysis_info.get('target_freq_energy', 0):.1f}%). Gửi đi...")
            
            # Lưu tên file hiện tại
            self.current_audio_file = chunk_id
            
            # Gửi dữ liệu âm thanh đến server qua WebSocket hoặc REST API
            if self.use_websocket and self.ws_connected:
                self.processing_status = "Đang gửi qua WebSocket"
                success = self.send_audio_via_websocket(window_data, float_timestamp)
                if success:
                    self.sent_success_count += 1
                    self.processing_status = "Đã gửi thành công"
                else:
                    self.sent_fail_count += 1
                    self.processing_status = "Lỗi gửi âm thanh"
            else:
                # Lưu thành file tạm và gửi qua REST API
                filepath = os.path.join(TEMP_DIR, f"{chunk_id}.wav")
                self.save_to_wav(window_data, filepath)
                self.processing_status = "Đang gửi qua REST API"
                success = self.send_audio_to_server(filepath, float_timestamp)
                if success:
                    self.sent_success_count += 1
                    self.processing_status = "Đã gửi thành công"
                else:
                    self.sent_fail_count += 1
                    self.processing_status = "Lỗi gửi âm thanh"
        else:
            self.processing_status = f"Bỏ qua (lý do: {analysis_info.get('reason', 'không xác định')})"
            logger.debug(f"Bỏ qua chunk âm thanh (lý do: {analysis_info.get('reason')})")
    
    def get_audio_as_base64(self, audio_data):
        """
        Chuyển đổi dữ liệu âm thanh thành chuỗi base64 của file WAV
        
        Args:
            audio_data (numpy.ndarray): Dữ liệu âm thanh
            
        Returns:
            str: Chuỗi base64 của dữ liệu WAV
        """
        # Chuyển đổi dữ liệu âm thanh thành định dạng WAV trong bộ nhớ
        buffer = BytesIO()
        wf = wave.open(buffer, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(self.audio.get_sample_size(self.format))
        wf.setframerate(self.sample_rate)
        wf.writeframes(audio_data.tobytes())
        wf.close()
        
        # Lấy dữ liệu WAV từ buffer
        buffer.seek(0)
        wav_data = buffer.read()
        
        # Mã hóa dữ liệu WAV dưới dạng base64
        encoded_data = base64.b64encode(wav_data).decode('utf-8')
        return encoded_data
    
    def save_to_wav(self, audio_data, filepath):
        """
        Lưu dữ liệu âm thanh vào file WAV.
        
        Args:
            audio_data (numpy.ndarray): Dữ liệu âm thanh
            filepath (str): Đường dẫn đến file đầu ra
        """
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            wf = wave.open(filepath, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())
            wf.close()
            logger.debug(f"Đã lưu âm thanh: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi lưu âm thanh: {e}")
            return False
    
    def send_audio_via_websocket(self, audio_data, timestamp):
        """
        Gửi dữ liệu âm thanh qua WebSocket theo định dạng yêu cầu của server
        
        Args:
            audio_data (numpy.ndarray): Dữ liệu âm thanh
            timestamp (float): Thời gian ghi âm
            
        Returns:
            bool: True nếu gửi thành công, False nếu không
        """
        if not self.ws_connected:
            logger.warning("Không có kết nối WebSocket, không thể gửi âm thanh")
            return False
        
        try:
            # Chuyển đổi dữ liệu âm thanh thành base64
            audio_base64 = self.get_audio_as_base64(audio_data)
            
            # Tạo message theo định dạng yêu cầu của server
            message = {
                'timestamp': timestamp,
                'sample_rate': self.sample_rate,
                'channels': self.channels,
                'audio_data': audio_base64
            }
            
            # Gửi qua WebSocket
            self.ws.send(json.dumps(message))
            logger.debug(f"Đã gửi âm thanh qua WebSocket lúc {timestamp}")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi gửi âm thanh qua WebSocket: {e}")
            return False
    
    def send_audio_to_server(self, filepath, timestamp):
        """
        Gửi file âm thanh đến server qua REST API
        
        Args:
            filepath (str): Đường dẫn đến file âm thanh
            timestamp (float): Thời gian ghi âm
            
        Returns:
            bool: True nếu gửi thành công, False nếu không
        """
        if not os.path.exists(filepath):
            logger.error(f"Không tìm thấy file âm thanh: {filepath}")
            return False
            
        try:
            # Gửi file qua REST API
            with open(filepath, 'rb') as audio_file:
                files = {
                    'audio': (os.path.basename(filepath), audio_file, 'audio/wav')
                }
                
                data = {
                    'timestamp': timestamp,
                    'device_id': DEVICE_ID,
                    'sample_rate': self.sample_rate,
                    'channels': self.channels
                }
                
                logger.debug(f"Đang gửi âm thanh đến server: {os.path.basename(filepath)}")
                success, response = make_api_request(
                    url=AUDIO_API_ENDPOINT,
                    method='POST',
                    data=data,
                    files=files
                )
                
                # Xóa file tạm sau khi gửi
                os.remove(filepath)
                
                if success:
                    logger.debug(f"Đã gửi âm thanh thành công")
                    return True
                else:
                    logger.error(f"Lỗi khi gửi âm thanh: {response}")
                    return False
                    
        except Exception as e:
            logger.error(f"Lỗi khi gửi âm thanh đến server: {e}")
            # Xóa file tạm nếu có lỗi
            if os.path.exists(filepath):
                os.remove(filepath)
            return False
    
    def capture_audio(self, duration=None):
        """
        Ghi âm trực tiếp (không sử dụng sliding window)
        
        Args:
            duration (int): Thời gian ghi âm (giây)
            
        Returns:
            tuple: (đường dẫn file, dữ liệu âm thanh) hoặc (None, None) nếu thất bại
        """
        if duration is None:
            duration = self.window_size
            
        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudio không khả dụng, không thể ghi âm trực tiếp")
            return None, None
            
        try:
            string_timestamp, _ = get_timestamp()
            filename = f"audio_{string_timestamp}.wav"
            filepath = os.path.join(AUDIO_DIR, filename)
            
            # Thiết lập ghi âm
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            logger.info(f"Bắt đầu ghi âm {duration} giây...")
            
            frames = []
            
            # Ghi âm trong thời gian duration
            for i in range(0, int(self.sample_rate / self.chunk_size * duration)):
                data = stream.read(self.chunk_size)
                frames.append(np.frombuffer(data, dtype=np.int16))
            
            logger.info("Ghi âm hoàn tất.")
            
            # Dừng và đóng luồng
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            # Chuyển đổi frames thành mảng numpy
            audio_data = np.concatenate(frames)
            
            # Lưu file âm thanh
            self.save_to_wav(audio_data, filepath)
            
            return filepath, audio_data
            
        except Exception as e:
            logger.error(f"Lỗi khi ghi âm trực tiếp: {e}")
            return None, None
            
    def capture_and_send_audio(self):
        """
        Ghi âm và gửi đến server
        
        Returns:
            bool: True nếu thành công, False nếu không
        """
        # Ghi âm
        audio_path, audio_data = self.capture_audio()
        
        if audio_path is None or audio_data is None:
            logger.error("Không thể ghi âm để gửi đến server")
            return False
        
        # Kiểm tra VAD và tần số nếu đã bật chế độ lọc
        if self.use_vad_filter:
            should_send, analysis_info = self.should_send_audio(audio_data)
            if not should_send:
                logger.info(f"Bỏ qua âm thanh đã thu (lý do: {analysis_info.get('reason')})")
                return False
            
        # Gửi âm thanh đến server
        _, timestamp = get_timestamp()
        if self.use_websocket and self.ws_connected:
            # Ưu tiên gửi qua WebSocket nếu có kết nối
            return self.send_audio_via_websocket(audio_data, timestamp)
        else:
            # Nếu không có kết nối WebSocket, gửi qua REST API
            return self.send_audio_to_server(audio_path, timestamp)


# Test module khi chạy trực tiếp
if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Audio client cho hệ thống giám sát trẻ em')
    parser.add_argument('--no-vad', action='store_true', help='Tắt tính năng lọc âm thanh VAD')
    parser.add_argument('--no-ws', action='store_true', help='Chỉ sử dụng REST API (không WebSocket)')
    args = parser.parse_args()

    # Khởi tạo client
    audio_client = AudioClient(
        use_websocket=not args.no_ws,
        use_vad_filter=not args.no_vad
    )
    
    # Bắt đầu client
    audio_client.start()
    
    try:
        # Cho WebSocket client chạy một lát
        logger.info("Giữ kết nối và ghi âm trong 60 giây...")
        logger.info(f"Chế độ lọc VAD: {'Tắt' if args.no_vad else 'Bật'}")
        logger.info(f"Chế độ WebSocket: {'Tắt' if args.no_ws else 'Bật'}")
        time.sleep(60)
        
        # Thử nghiệm ghi âm trực tiếp và gửi
        logger.info("Thử nghiệm ghi âm trực tiếp và gửi...")
        success = audio_client.capture_and_send_audio()
        if success:
            logger.info("✓ Thành công")
        else:
            logger.error("✗ Thất bại")
        
    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu dừng")
    finally:
        # Dừng client
        audio_client.stop()
        logger.info("Đã kết thúc thử nghiệm")