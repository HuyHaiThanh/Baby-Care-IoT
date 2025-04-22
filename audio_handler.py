# File: audio_handler.py
# Module xử lý ghi âm trên Raspberry Pi sử dụng sliding window

import os
import time
import datetime
import wave
import numpy as np
import threading
import queue
from io import BytesIO
import base64
from config import AUDIO_DIR

# Flag for checking if PyAudio is available
PYAUDIO_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
    print("Đã phát hiện PyAudio.")
except ImportError:
    print("CẢNH BÁO: Không tìm thấy thư viện PyAudio. Sẽ chỉ tạo file âm thanh giả lập.")

class AudioRecorder:
    """
    Ghi âm liên tục sử dụng kỹ thuật sliding window.
    
    Lớp này ghi âm liên tục và xử lý theo các cửa sổ chồng lấp.
    Với cài đặt mặc định, nó tạo ra các đoạn âm thanh 3 giây với bước nhảy 1 giây,
    nghĩa là có 2 giây chồng lấp giữa các đoạn liên tiếp.
    Được tối ưu cho Raspberry Pi 2B.
    """
    def __init__(self, chunk_size=1024, sample_rate=16000, channels=1, 
                 window_size=3, slide_size=1, format=None,
                 save_audio=True, audio_dir=AUDIO_DIR, callback=None):
        """
        Khởi tạo AudioRecorder với các tham số đã chỉ định.
        
        Args:
            chunk_size (int): Số lượng khung âm thanh trong mỗi buffer
            sample_rate (int): Tần số lấy mẫu theo Hz (mặc định 16000)
            channels (int): Số kênh âm thanh (1=mono, 2=stereo)
            window_size (int): Kích thước của mỗi đoạn âm thanh tính theo giây (mặc định 3)
            slide_size (int): Khoảng cách giữa các cửa sổ liên tiếp tính theo giây (mặc định 1)
            format: Định dạng PyAudio (nếu None, sẽ dùng paInt16)
            save_audio (bool): Có lưu file âm thanh không
            audio_dir (str): Thư mục lưu các file âm thanh
            callback (function): Hàm callback nhận audio_data và chunk_id khi có audio mới
        """
        if not PYAUDIO_AVAILABLE:
            print("CẢNH BÁO: PyAudio không khả dụng, một số tính năng sẽ bị hạn chế")
            return
        
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = pyaudio.paInt16 if format is None else format
        self.window_size = window_size  # theo giây
        self.slide_size = slide_size    # theo giây
        self.save_audio = save_audio
        self.audio_dir = audio_dir
        self.user_callback = callback
        
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.frames_per_window = int(sample_rate * window_size)  # Tổng frames trong cửa sổ (ví dụ: 48000 frames cho 3s ở 16kHz)
        self.frames_per_slide = int(sample_rate * slide_size)    # Frames để trượt (ví dụ: 16000 frames cho 1s ở 16kHz)
        self.chunk_queue = queue.Queue()
        self.save_counter = 0
        self.processing_thread = None
        
        # Tạo thư mục lưu âm thanh nếu cần
        if self.save_audio and not os.path.exists(self.audio_dir):
            os.makedirs(self.audio_dir, exist_ok=True)
            
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
            print("Đã bắt đầu ghi âm với chế độ sliding window")
            return True
            
        except Exception as e:
            print(f"Lỗi khi bắt đầu ghi âm: {e}")
            self.is_recording = False
            return False
        
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
                            print("Không đủ dữ liệu cho một cửa sổ đầy đủ. Đang đợi thêm dữ liệu...")
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
        Xử lý một cửa sổ 3 giây dữ liệu âm thanh.
        
        Phương thức này xử lý mỗi cửa sổ trượt của dữ liệu âm thanh.
        Ví dụ, với cửa sổ 3 giây và bước trượt 1 giây:
          - Cửa sổ đầu tiên: 0-3 giây
          - Cửa sổ thứ hai: 1-4 giây
          - Cửa sổ thứ ba: 2-5 giây
          
        Args:
            window_data (numpy.ndarray): Dữ liệu âm thanh cho cửa sổ hiện tại (3 giây)
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        chunk_id = f"audio_chunk_{timestamp}_{self.save_counter}"
        self.chunk_queue.put(window_data)
        
        # Lưu đoạn âm thanh nếu cần
        if self.save_audio:
            # Sử dụng thread riêng để lưu âm thanh để tránh blocking
            save_thread = threading.Thread(
                target=self.save_to_wav, 
                args=(window_data, f"{chunk_id}.wav")
            )
            save_thread.daemon = True
            save_thread.start()
        
        # Gọi callback của người dùng nếu có
        if self.user_callback:
            try:
                self.user_callback(window_data, chunk_id)
            except Exception as e:
                print(f"Lỗi trong user callback: {e}")
        
        self.save_counter += 1
    
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
        
    def save_to_wav(self, audio_data, filename):
        """
        Lưu dữ liệu âm thanh vào file WAV.
        
        Args:
            audio_data (numpy.ndarray): Dữ liệu âm thanh
            filename (str): Tên file đầu ra
        """
        try:
            filepath = os.path.join(self.audio_dir, filename)
            wf = wave.open(filepath, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())
            wf.close()
            print(f"Đã lưu âm thanh: {filename}")
        except Exception as e:
            print(f"Lỗi khi lưu âm thanh: {e}")
        
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
        
        print("Đã dừng ghi âm")
        
    def close(self):
        """
        Giải phóng tài nguyên và chấm dứt PyAudio.
        Nên được gọi khi ứng dụng kết thúc.
        """
        self.stop_recording()
        if hasattr(self, 'audio') and self.audio:
            self.audio.terminate()


def capture_audio(duration=5):
    """
    Ghi âm từ microphone (phương thức cũ, được giữ lại để tương thích ngược)
    
    Args:
        duration (int): Thời gian ghi âm tính theo giây
        
    Returns:
        str: Đường dẫn tới file âm thanh, hoặc None nếu không thành công
    """
    # Tạo thư mục lưu âm thanh nếu chưa tồn tại
    os.makedirs(AUDIO_DIR, exist_ok=True)
    
    # Tạo tên file với timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"audio_{timestamp}.wav"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    try:
        if PYAUDIO_AVAILABLE:
            # Thiết lập các thông số ghi âm
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000  # 16kHz
            CHUNK = 1024
            
            # Khởi tạo PyAudio
            audio = pyaudio.PyAudio()
            
            print(f"Bắt đầu ghi âm {duration} giây...")
            
            # Mở luồng ghi âm
            stream = audio.open(format=FORMAT, channels=CHANNELS,
                               rate=RATE, input=True,
                               frames_per_buffer=CHUNK)
            
            frames = []
            
            # Ghi âm trong thời gian duration
            for i in range(0, int(RATE / CHUNK * duration)):
                data = stream.read(CHUNK)
                frames.append(data)
            
            print("Ghi âm hoàn tất.")
            
            # Dừng và đóng luồng
            stream.stop_stream()
            stream.close()
            audio.terminate()
            
            # Lưu file âm thanh
            waveFile = wave.open(filepath, 'wb')
            waveFile.setnchannels(CHANNELS)
            waveFile.setsampwidth(audio.get_sample_size(FORMAT))
            waveFile.setframerate(RATE)
            waveFile.writeframes(b''.join(frames))
            waveFile.close()
            
            print(f"Đã lưu âm thanh: {filename}")
            
        else:
            # Tạo file âm thanh giả lập (chỉ dành cho mục đích kiểm thử)
            print("Không tìm thấy PyAudio, tạo file âm thanh giả lập...")
            
            # Tạo dữ liệu giả lập (1 giây tín hiệu sin 440Hz)
            framerate = 16000  # 16kHz
            amplitude = np.iinfo(np.int16).max / 2
            t = np.linspace(0, duration, framerate * duration)
            signal = amplitude * np.sin(2 * np.pi * 440 * t)
            
            # Thêm một số nhiễu giả lập
            noise = np.random.normal(0, amplitude / 10, len(signal))
            signal = signal + noise
            signal = signal.astype(np.int16)
            
            # Lưu file wav
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 2 bytes per sample (16-bit)
                wf.setframerate(framerate)
                wf.writeframes(signal.tobytes())
                
            print(f"Đã lưu âm thanh giả lập: {filename}")
        
        return filepath
    except Exception as e:
        print(f"Lỗi khi ghi âm: {e}")
        return None


# Test module khi chạy trực tiếp
if __name__ == "__main__":
    # Test recording với sliding window
    print("Test recording với sliding window (3s window, 1s slide)")
    recorder = AudioRecorder(window_size=3, slide_size=1)
    
    # Định nghĩa callback để kiểm tra
    def on_audio_ready(audio_data, chunk_id):
        print(f"Chunk mới sẵn sàng: {chunk_id}, độ dài: {len(audio_data)} mẫu")
        
    recorder.user_callback = on_audio_ready
    
    if PYAUDIO_AVAILABLE:
        recorder.start_recording()
        print("Ghi âm trong 10 giây...")
        time.sleep(10)  # Ghi âm trong 10 giây
        recorder.stop_recording()
        recorder.close()
        print("Test hoàn tất")
    else:
        print("Không thể test sliding window do thiếu PyAudio")
        
    # Test phương thức capture_audio cũ
    print("\nTest phương thức capture_audio cũ")
    audio_path = capture_audio(3)  # Ghi âm 3 giây
    if audio_path:
        print(f"Đã lưu âm thanh tại: {audio_path}")
    else:
        print("Không thể ghi âm")