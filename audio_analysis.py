# File: audio_analysis.py
# Module phân tích âm thanh để phát hiện tiếng khóc em bé với Voice Activity Detection (VAD)
# và lọc tần số trong khoảng 250-750Hz

import os
import numpy as np
import wave
import scipy.signal as signal
from scipy.fft import fft, fftfreq
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('audio_analysis')

# Cấu hình cho hệ thống phát hiện tiếng khóc
FREQ_MIN = 250  # Tần số thấp nhất (Hz)
FREQ_MAX = 750  # Tần số cao nhất (Hz)
ENERGY_THRESHOLD = 0.01  # Ngưỡng năng lượng để phát hiện âm thanh
VAD_THRESHOLD = 0.15  # Ngưỡng VAD

def load_wav_file(file_path):
    """
    Đọc file WAV và trả về dữ liệu dạng numpy array
    
    Args:
        file_path: Đường dẫn tới file WAV
        
    Returns:
        tuple: (sample_rate, audio_data dạng numpy array)
    """
    try:
        with wave.open(file_path, 'rb') as wav_file:
            # Lấy thông số
            sample_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            n_channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            
            # Đọc dữ liệu
            frames = wav_file.readframes(n_frames)
            
            # Chuyển đổi bytes thành numpy array
            if sampwidth == 2:  # 16-bit
                dtype = np.int16
            elif sampwidth == 4:  # 32-bit
                dtype = np.int32
            else:  # Assume 8-bit
                dtype = np.uint8
                
            audio_data = np.frombuffer(frames, dtype=dtype)
            
            # Nếu là stereo, chuyển về mono bằng cách lấy trung bình 2 kênh
            if n_channels == 2:
                audio_data = audio_data.reshape(-1, 2).mean(axis=1)
                
            return sample_rate, audio_data
            
    except Exception as e:
        logger.error(f"Lỗi khi đọc file WAV: {e}")
        return None, None

def voice_activity_detection(audio_data, sample_rate, frame_duration=0.03, threshold=VAD_THRESHOLD):
    """
    Phát hiện các đoạn có hoạt động âm thanh (VAD)
    
    Args:
        audio_data: Dữ liệu âm thanh
        sample_rate: Tần số lấy mẫu
        frame_duration: Độ dài mỗi khung (giây)
        threshold: Ngưỡng năng lượng để xác định có hoạt động âm thanh
        
    Returns:
        list: Danh sách các khung có hoạt động âm thanh (True/False)
        numpy array: Mức năng lượng theo khung
    """
    # Chuẩn hóa âm thanh
    audio_data = audio_data / (np.max(np.abs(audio_data)) + 1e-10)
    
    # Tính kích thước khung
    frame_size = int(sample_rate * frame_duration)
    num_frames = int(np.ceil(len(audio_data) / frame_size))
    
    # Tạo mảng lưu mức năng lượng từng khung
    frame_energy = np.zeros(num_frames)
    
    # Tính năng lượng cho từng khung
    for i in range(num_frames):
        start = i * frame_size
        end = min(start + frame_size, len(audio_data))
        frame = audio_data[start:end]
        frame_energy[i] = np.mean(frame**2)
    
    # Áp dụng ngưỡng để xác định các khung có hoạt động âm thanh
    vad_mask = frame_energy > threshold
    
    return vad_mask, frame_energy

def frequency_analysis(audio_data, sample_rate, freq_min=FREQ_MIN, freq_max=FREQ_MAX):
    """
    Phân tích tần số và xác định phần trăm năng lượng âm thanh trong dải tần số quan tâm
    
    Args:
        audio_data: Dữ liệu âm thanh
        sample_rate: Tần số lấy mẫu
        freq_min: Tần số thấp nhất quan tâm (Hz)
        freq_max: Tần số cao nhất quan tâm (Hz)
        
    Returns:
        float: Phần trăm năng lượng âm thanh trong dải tần số quan tâm
    """
    # Tính FFT
    n = len(audio_data)
    yf = fft(audio_data)
    xf = fftfreq(n, 1 / sample_rate)
    
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

def extract_audio_features(sample_rate, audio_data):
    """
    Trích xuất các đặc trưng âm thanh cho tiếng khóc em bé
    
    Args:
        sample_rate: Tần số lấy mẫu
        audio_data: Dữ liệu âm thanh dạng numpy array
        
    Returns:
        dict: Các đặc trưng âm thanh
    """
    # Chuẩn hóa dữ liệu
    normalized_data = audio_data / (np.max(np.abs(audio_data)) + 1e-10)
    
    # Tính các đặc trưng
    features = {}
    
    # Độ lớn trung bình (energy)
    features['energy'] = np.mean(np.abs(normalized_data))
    
    # Độ biến thiên (variance)
    features['variance'] = np.var(normalized_data)
    
    # Zero crossing rate (tần suất đổi dấu)
    zero_crossings = np.sum(np.abs(np.diff(np.signbit(normalized_data))))
    features['zero_crossing_rate'] = zero_crossings / len(normalized_data)
    
    # Phân tích VAD
    vad_mask, frame_energy = voice_activity_detection(normalized_data, sample_rate)
    features['vad_active_frames_ratio'] = np.mean(vad_mask)
    
    # Phân tích tần số
    target_freq_energy = frequency_analysis(
        normalized_data, sample_rate, freq_min=FREQ_MIN, freq_max=FREQ_MAX
    )
    features['target_frequency_energy_percent'] = target_freq_energy
    
    # Kiểm tra các đặc trưng cho tiếng khóc
    features['high_freq_energy'] = target_freq_energy > 40  # 40% năng lượng trong dải tần số quan tâm
    features['high_variance'] = features['variance'] > 0.05
    features['high_energy'] = features['energy'] > 0.2
    
    return features

def detect_baby_crying(audio_data=None, audio_file=None, threshold=0.6):
    """
    Phân tích âm thanh để phát hiện tiếng khóc của em bé
    
    Args:
        audio_data: Dữ liệu âm thanh dạng numpy array (nếu có)
        audio_file: Đường dẫn tới file âm thanh (nếu không có audio_data)
        threshold: Ngưỡng xác định tiếng khóc (0.0-1.0)
        
    Returns:
        tuple: (is_crying (bool), features (dict))
    """
    sample_rate = None
    
    # Đọc dữ liệu âm thanh nếu cần
    if audio_data is None:
        if audio_file is None:
            logger.error("Phải cung cấp audio_data hoặc audio_file")
            return False, {}
            
        logger.info(f"Phân tích âm thanh từ file: {os.path.basename(audio_file)}")
        sample_rate, audio_data = load_wav_file(audio_file)
        
        if sample_rate is None or audio_data is None:
            logger.error("Không thể đọc file âm thanh")
            return False, {}
    else:
        # Nếu chỉ có audio_data, giả định sample_rate là 16kHz (tần số phổ biến)
        sample_rate = 16000
        if audio_file:
            logger.info(f"Phân tích âm thanh: {os.path.basename(audio_file)}")
            
    # Kiểm tra năng lượng âm thanh tổng thể
    energy = np.mean(np.abs(audio_data))
    if energy < ENERGY_THRESHOLD:
        logger.info(f"Âm thanh quá yếu (energy={energy:.6f}), bỏ qua phân tích")
        return False, {'energy': energy}
        
    # Trích xuất đặc trưng
    features = extract_audio_features(sample_rate, audio_data)
    
    # Tính điểm xác suất tiếng khóc
    crying_score = 0.0
    
    if features['high_freq_energy']:
        crying_score += 0.5  # Tăng trọng số cho năng lượng trong dải tần số 250-750Hz
    
    if features['high_variance']:
        crying_score += 0.3
    
    if features['high_energy']:
        crying_score += 0.2
        
    features['crying_score'] = crying_score
    
    # Xác định có phải tiếng khóc không
    is_crying = crying_score > threshold
    features['is_crying'] = is_crying
    
    if is_crying:
        logger.info(f"Phát hiện tiếng khóc! (độ tin cậy: {crying_score:.2f})")
        logger.info(f"Phần trăm năng lượng trong dải 250-750Hz: {features['target_frequency_energy_percent']:.2f}%")
    else:
        logger.info(f"Không phát hiện tiếng khóc (điểm số: {crying_score:.2f})")
        
    return is_crying, features

# Test module khi chạy trực tiếp
if __name__ == "__main__":
    from audio_handler import AudioRecorder
    import time
    
    print("Thử nghiệm phát hiện tiếng khóc với VAD và phân tích tần số 250-750Hz")
    
    # Test với file
    import sys
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        if os.path.exists(audio_file):
            is_crying, features = detect_baby_crying(audio_file=audio_file)
            print(f"Kết quả phân tích file '{os.path.basename(audio_file)}':")
            print(f"- Tiếng khóc: {'Có' if is_crying else 'Không'}")
            print(f"- Điểm số: {features.get('crying_score', 0):.2f}")
            print(f"- Năng lượng trong dải 250-750Hz: {features.get('target_frequency_energy_percent', 0):.2f}%")
            print(f"- VAD: {features.get('vad_active_frames_ratio', 0):.2f}")
    else:
        # Test ghi âm realtime
        def process_audio(audio_data, chunk_id):
            is_crying, features = detect_baby_crying(audio_data=audio_data)
            print(f"\nPhân tích chunk {chunk_id}:")
            print(f"- Tiếng khóc: {'Có' if is_crying else 'Không'}")
            print(f"- Điểm số: {features.get('crying_score', 0):.2f}")
            print(f"- Năng lượng trong dải 250-750Hz: {features.get('target_frequency_energy_percent', 0):.2f}%")
            print(f"- VAD: {features.get('vad_active_frames_ratio', 0):.2f}")
        
        recorder = AudioRecorder(window_size=3, slide_size=1, callback=process_audio)
        if hasattr(recorder, 'start_recording'):
            print("Ghi âm và phân tích trong 15 giây...")
            recorder.start_recording()
            try:
                time.sleep(15)
            finally:
                recorder.stop_recording()
                recorder.close()
        else:
            print("Không thể khởi tạo AudioRecorder, kiểm tra PyAudio")