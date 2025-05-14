#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import signal
import argparse
import logging
import atexit
import socket
from firebase_device_manager import initialize_device, update_streaming_status, get_ngrok_url
from virtual_camera import find_available_camera_devices, VirtualCameraManager

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('video_streaming')

# Đường dẫn lưu trữ HLS
HLS_OUTPUT_DIR = "/var/www/html"

# Biến toàn cục lưu trữ thông tin thiết bị và token
device_uuid = None
id_token = None

def get_ip_address():
    """Lấy địa chỉ IP của Raspberry Pi"""
    try:
        # Tạo socket và kết nối đến Google DNS để lấy IP cục bộ
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        logger.warning(f"Không thể lấy địa chỉ IP: {str(e)}")
        return "localhost"

class VideoStreamManager:
    def __init__(self, video_device="/dev/video0", width=640, height=480, framerate=30):
        """
        Khởi tạo quản lý luồng streaming video
        
        Args:
            video_device: Thiết bị camera để streaming
            width: Chiều rộng video
            height: Chiều cao video
            framerate: Tốc độ khung hình
        """
        self.video_device = video_device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.streaming_process = None
        self.running = False
        self.ip_address = get_ip_address()
        # Đăng ký hàm cleanup khi tắt ứng dụng
        atexit.register(self.cleanup)
    
    def start_streaming(self):
        """
        Bắt đầu streaming HLS từ thiết bị camera
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        if self.streaming_process:
            return True
        
        logger.info(f"Bắt đầu streaming HLS từ {self.video_device}")
        
        try:
            # Đảm bảo thư mục đầu ra tồn tại
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                         capture_output=True, text=True)
            
            # Kiểm tra định dạng đầu vào của thiết bị
            try:
                format_info = subprocess.run(["v4l2-ctl", "-d", self.video_device, "--list-formats"], 
                                          capture_output=True, text=True)
                supports_mjpeg = "MJPEG" in format_info.stdout
                supports_raw = "Raw" in format_info.stdout
                logger.info(f"Định dạng hỗ trợ: MJPEG={supports_mjpeg}, Raw={supports_raw}")
            except Exception:
                # Mặc định là sử dụng cả hai định dạng
                supports_mjpeg = True
                supports_raw = True
            
            # Sử dụng GStreamer với định dạng phù hợp
            if supports_mjpeg:
                # Pipeline cho MJPEG
                command = [
                    "sudo", "gst-launch-1.0",
                    "v4l2src", f"device={self.video_device}", "!", 
                    f"image/jpeg,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                    "jpegdec", "!",
                    "videoconvert", "!",
                    "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
                    "mpegtsmux", "!",
                    "hlssink", 
                    f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                    f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                    "target-duration=2", 
                    "max-files=3"
                ]
            else:
                # Pipeline cho raw format
                command = [
                    "sudo", "gst-launch-1.0",
                    "v4l2src", f"device={self.video_device}", "!", 
                    f"video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                    "videoconvert", "!",
                    "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
                    "mpegtsmux", "!",
                    "hlssink", 
                    f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                    f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                    "target-duration=2", 
                    "max-files=3"
                ]
            
            logger.info("Sử dụng lệnh: " + " ".join(command))
            
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(3)  # Đợi để GStreamer bắt đầu
            
            if self.streaming_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.streaming_process.communicate()
                logger.error(f"Không thể bắt đầu streaming: {stderr.decode()}")
                return self.start_streaming_alternative()
            
            # Cập nhật trạng thái streaming trên Firebase
            if device_uuid and id_token:
                # Lấy URL ngrok mới
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    # Thêm đường dẫn đến playlist.m3u8
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    logger.info(f"Stream URL: {stream_url}")
                    # Cập nhật trạng thái online và URI
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    # Không có URL ngrok, chỉ cập nhật trạng thái online
                    update_streaming_status(device_uuid, id_token, True)
            
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu thành công: {stream_url}")
            self.running = True
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu streaming HLS: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return self.start_streaming_alternative()
    
    def start_streaming_alternative(self):
        """
        Phương pháp thay thế để streaming nếu phương pháp đầu tiên thất bại
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        logger.info("Đang thử phương pháp thay thế để streaming với ffmpeg...")
        
        try:
            # Sử dụng ffmpeg thay vì GStreamer
            # Thử với định dạng mjpeg trước
            command = [
                "sudo", "ffmpeg", 
                "-f", "v4l2", 
                "-input_format", "mjpeg",  # Thử với mjpeg
                "-i", self.video_device, 
                "-c:v", "libx264", 
                "-preset", "ultrafast", 
                "-tune", "zerolatency", 
                "-f", "hls", 
                "-hls_time", "2", 
                "-hls_list_size", "3", 
                "-hls_flags", "delete_segments",
                f"{HLS_OUTPUT_DIR}/playlist.m3u8"
            ]
            
            logger.info("Sử dụng lệnh ffmpeg: " + " ".join(command))
            
            self.streaming_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(3)
            
            if self.streaming_process.poll() is not None:
                # MJPEG không hoạt động, thử lại không chỉ định định dạng đầu vào
                stdout, stderr = self.streaming_process.communicate()
                logger.warning(f"MJPEG không hoạt động, thử lại không chỉ định định dạng: {stderr.decode()}")
                
                # Phương pháp thay thế không chỉ định định dạng
                command = [
                    "sudo", "ffmpeg", 
                    "-f", "v4l2", 
                    "-i", self.video_device, 
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-tune", "zerolatency", 
                    "-f", "hls", 
                    "-hls_time", "2", 
                    "-hls_list_size", "3", 
                    "-hls_flags", "delete_segments",
                    f"{HLS_OUTPUT_DIR}/playlist.m3u8"
                ]
                
                logger.info("Sử dụng lệnh ffmpeg thay thế: " + " ".join(command))
                
                self.streaming_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                time.sleep(3)
                
                if self.streaming_process.poll() is not None:
                    stdout, stderr = self.streaming_process.communicate()
                    logger.error(f"Phương pháp thay thế cũng thất bại: {stderr.decode()}")
                    return False
            
            # Cập nhật trạng thái streaming trên Firebase
            if device_uuid and id_token:
                # Lấy URL ngrok mới
                ngrok_url = get_ngrok_url()
                if ngrok_url:
                    stream_url = f"{ngrok_url}/playlist.m3u8"
                    logger.info(f"Stream URL: {stream_url}")
                    update_streaming_status(device_uuid, id_token, True, stream_url)
                else:
                    update_streaming_status(device_uuid, id_token, True)
            
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            logger.info(f"Streaming HLS đã bắt đầu với ffmpeg: {stream_url}")
            self.running = True
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi sử dụng phương pháp thay thế: {str(e)}")
            if self.streaming_process:
                self.streaming_process.terminate()
                self.streaming_process = None
            return False
    
    def stop_streaming(self):
        """Dừng quá trình streaming HLS"""
        if self.streaming_process:
            logger.info("Đang dừng quá trình streaming HLS...")
            self.streaming_process.terminate()
            try:
                self.streaming_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.streaming_process.kill()
            self.streaming_process = None
            
            # Cập nhật trạng thái offline trên Firebase
            if device_uuid and id_token:
                update_streaming_status(device_uuid, id_token, False)
        
        self.running = False
    
    def start(self):
        """
        Bắt đầu quá trình streaming
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        if self.running:
            logger.info("Streaming đã đang chạy")
            return True
        
        # Kiểm tra thiết bị camera
        if not os.path.exists(self.video_device):
            logger.error(f"Thiết bị camera {self.video_device} không tồn tại")
            return False
        
        return self.start_streaming()
    
    def stop(self):
        """Dừng quá trình streaming"""
        self.stop_streaming()
        logger.info("Đã dừng streaming hoàn toàn")
        
    def cleanup(self):
        """Dọn dẹp khi tắt ứng dụng"""
        self.stop()

def direct_stream(physical_device, width=640, height=480, framerate=30, no_firebase=False):
    """
    Streaming trực tiếp từ thiết bị camera vật lý
    
    Args:
        physical_device: Thiết bị camera vật lý
        width: Chiều rộng video
        height: Chiều cao video
        framerate: Tốc độ khung hình
        no_firebase: Không sử dụng Firebase
        
    Returns:
        subprocess.Popen: Process streaming
    """
    logger.info(f"Bắt đầu streaming trực tiếp từ camera vật lý {physical_device}...")
    
    # Đảm bảo thư mục đầu ra tồn tại
    os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
    subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                 capture_output=True, text=True)
    
    # Lệnh GStreamer để streaming
    command = [
        "sudo", "gst-launch-1.0",
        "v4l2src", f"device={physical_device}", "!", 
        f"video/x-raw,width={width},height={height},framerate={framerate}/1", "!",
        "videoconvert", "!",
        "x264enc", "tune=zerolatency", "bitrate=512", "speed-preset=ultrafast", "key-int-max=30", "!", 
        "mpegtsmux", "!",
        "hlssink", 
        f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
        f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
        "target-duration=2", 
        "max-files=3"
    ]
    
    # Thực thi lệnh
    streaming_process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    time.sleep(3)  # Đợi để bắt đầu
    
    # Cập nhật trạng thái streaming trên Firebase nếu streaming thành công
    if streaming_process.poll() is None and not no_firebase and device_uuid and id_token:
        ngrok_url = get_ngrok_url()
        if ngrok_url:
            stream_url = f"{ngrok_url}/playlist.m3u8"
            update_streaming_status(device_uuid, id_token, True, stream_url)
    
    logger.info("Streaming HLS đã bắt đầu. Nhấn Ctrl+C để dừng.")
    return streaming_process

def main():
    """Hàm chính để chạy dịch vụ streaming"""
    global device_uuid, id_token
    
    parser = argparse.ArgumentParser(description='Video streaming với HLS')
    parser.add_argument('--physical-device', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual', action='store_true', help='Sử dụng thiết bị camera ảo')
    parser.add_argument('--width', type=int, default=640, help='Chiều rộng video')
    parser.add_argument('--height', type=int, default=480, help='Chiều cao video')
    parser.add_argument('--framerate', type=int, default=30, help='Tốc độ khung hình')
    parser.add_argument('--no-firebase', action='store_true', help='Không sử dụng Firebase')
    
    args = parser.parse_args()
    
    # Tự động phát hiện thiết bị camera nếu không được chỉ định
    if not args.physical_device:
        available_cameras = find_available_camera_devices()
        if available_cameras:
            args.physical_device = available_cameras[0]
            logger.info(f"Tự động phát hiện camera: {args.physical_device}")
        else:
            args.physical_device = '/dev/video0'
            logger.warning(f"Không tìm thấy camera. Sử dụng mặc định: {args.physical_device}")
    
    # Khởi tạo thiết bị trên Firebase (trừ khi có tùy chọn --no-firebase)
    if not args.no_firebase:
        logger.info("Đang khởi tạo thiết bị trên Firebase...")
        device_uuid, id_token = initialize_device()
        if not device_uuid or not id_token:
            logger.warning("Không thể khởi tạo thiết bị trên Firebase. Tiếp tục mà không có Firebase.")
            args.no_firebase = True
    
    # Xử lý tín hiệu kết thúc (Ctrl+C)
    def signal_handler(sig, frame):
        logger.info("Đã nhận tín hiệu ngắt. Đang dừng dịch vụ...")
        if args.virtual and virtual_camera:
            virtual_camera.stop()
        if stream_manager:
            stream_manager.stop()
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Biến lưu các đối tượng quản lý
    virtual_camera = None
    stream_manager = None
    streaming_process = None
    
    try:
        if args.virtual:
            # Sử dụng camera ảo
            virtual_camera = VirtualCameraManager(physical_device=args.physical_device)
            success, device_path = virtual_camera.start()
            
            if success:
                logger.info(f"Đã tạo camera ảo thành công: {device_path}")
                # Streaming từ camera ảo
                stream_manager = VideoStreamManager(
                    video_device=device_path,
                    width=args.width,
                    height=args.height,
                    framerate=args.framerate
                )
                
                if not stream_manager.start():
                    logger.error("Không thể bắt đầu streaming từ camera ảo")
                    return
                
                # Giữ cho chương trình chạy
                while stream_manager.running:
                    time.sleep(1)
            else:
                logger.warning(f"Không thể tạo camera ảo. Sử dụng thiết bị gốc: {device_path}")
                # Stream trực tiếp từ thiết bị gốc
                streaming_process = direct_stream(
                    physical_device=device_path,
                    width=args.width,
                    height=args.height,
                    framerate=args.framerate,
                    no_firebase=args.no_firebase
                )
                # Đợi tiến trình streaming kết thúc
                streaming_process.wait()
        else:
            # Stream trực tiếp từ camera vật lý
            streaming_process = direct_stream(
                physical_device=args.physical_device,
                width=args.width,
                height=args.height,
                framerate=args.framerate,
                no_firebase=args.no_firebase
            )
            # Đợi tiến trình streaming kết thúc
            streaming_process.wait()
    
    except KeyboardInterrupt:
        logger.info("Đã nhận ngắt từ bàn phím. Đang dừng dịch vụ...")
    finally:
        # Dừng các tiến trình và dọn dẹp
        if args.virtual and virtual_camera:
            virtual_camera.stop()
        
        if stream_manager:
            stream_manager.stop()
        
        if streaming_process and streaming_process.poll() is None:
            streaming_process.terminate()
            try:
                streaming_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                streaming_process.kill()
        
        # Đảm bảo cập nhật trạng thái offline
        if not args.no_firebase and device_uuid and id_token:
            update_streaming_status(device_uuid, id_token, False)

if __name__ == "__main__":
    main()