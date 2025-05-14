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
        
        # Kiểm tra xem thiết bị là camera thực hay thiết bị ảo
        try:
            device_info = subprocess.run(
                ["v4l2-ctl", "-d", video_device, "--info"],
                capture_output=True,
                text=True,
                stderr=subprocess.DEVNULL
            ).stdout
            # Nếu trong thông tin thiết bị có từ khóa loopback thì đây là thiết bị ảo
            self.is_virtual_device = "loopback" in device_info.lower() or "v4l2loopback" in device_info.lower()
            # Kiểm tra thêm từ số thiết bị
            if not self.is_virtual_device:
                video_num = int(video_device.split('video')[-1])
                self.is_virtual_device = video_num >= 10  # Thiết bị từ video10 trở lên thường là thiết bị ảo
        except Exception:
            # Nếu không kiểm tra được, giả định từ tên thiết bị
            self.is_virtual_device = int(video_device.split('video')[-1]) >= 10
        
        logger.info(f"Thiết bị {video_device} được xác định là {'thiết bị ảo' if self.is_virtual_device else 'camera thực'}")
        
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
            # Đảm bảo thư mục đầu ra tồn tại và có quyền truy cập đầy đủ
            os.makedirs(HLS_OUTPUT_DIR, exist_ok=True)
            subprocess.run(["sudo", "chmod", "-R", "777", HLS_OUTPUT_DIR], 
                         capture_output=True, text=True)
            
            # Xóa các file cũ nếu có
            try:
                subprocess.run(["sudo", "rm", "-f", f"{HLS_OUTPUT_DIR}/*.ts", f"{HLS_OUTPUT_DIR}/*.m3u8"], 
                              capture_output=True, shell=True)
            except Exception:
                pass
            
            # Cấu hình HLS cho VLC với UDP thay vì file segment
            if self.is_virtual_device:
                # Thiết bị ảo - sử dụng video/x-raw
                logger.info("Sử dụng định dạng video/x-raw cho thiết bị ảo với UDP Streaming")
                command = [
                    "sudo", "gst-launch-1.0",
                    "v4l2src", f"device={self.video_device}", "!", 
                    f"video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                    "videoconvert", "!",
                    "x264enc", "tune=zerolatency", "bitrate=2048", "speed-preset=ultrafast", 
                    "key-int-max=15", "!",
                    "mpegtsmux", "!",
                    "hlssink", 
                    f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                    f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                    "target-duration=1", 
                    "max-files=15"
                ]
            else:
                # Thiết bị thật - sử dụng image/jpeg
                logger.info("Sử dụng định dạng image/jpeg cho camera thực với UDP Streaming")
                command = [
                    "sudo", "gst-launch-1.0",
                    "v4l2src", f"device={self.video_device}", "!", 
                    f"image/jpeg,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                    "jpegdec", "!",
                    "videoconvert", "!",
                    "x264enc", "tune=zerolatency", "bitrate=2048", "speed-preset=ultrafast", 
                    "key-int-max=15", "!",
                    "mpegtsmux", "!",
                    "hlssink", 
                    f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                    f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                    "target-duration=1", 
                    "max-files=15"
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
                
                # Thử với định dạng ngược lại
                logger.info("Thử lại với định dạng khác...")
                
                if self.is_virtual_device:
                    # Thử với một số định dạng khác
                    formats_to_try = [
                        "video/x-raw,format=YUY2",  # YUY2 thường được hỗ trợ rộng rãi
                        "video/x-raw,format=RGB",   # RGB
                        "video/x-raw"               # Để GStreamer tự động xác định
                    ]
                    
                    for video_format in formats_to_try:
                        logger.info(f"Thử với định dạng: {video_format}")
                        command = [
                            "sudo", "gst-launch-1.0",
                            "v4l2src", f"device={self.video_device}", "!", 
                            f"{video_format},width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                            "videoconvert", "!",
                            "x264enc", "tune=zerolatency", "bitrate=2048", "speed-preset=ultrafast", 
                            "key-int-max=15", "!",
                            "mpegtsmux", "!",
                            "hlssink", 
                            f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                            f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                            "target-duration=1", 
                            "max-files=15"
                        ]
                        
                        logger.info("Sử dụng lệnh: " + " ".join(command))
                        
                        self.streaming_process = subprocess.Popen(
                            command,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )
                        
                        time.sleep(3)
                        
                        if self.streaming_process.poll() is None:
                            # Hoạt động, thoát khỏi vòng lặp
                            logger.info(f"Định dạng {video_format} hoạt động!")
                            
                            # Tạo symbolic link để các trình phát dễ tìm file m3u8
                            try:
                                subprocess.run(["sudo", "ln", "-sf", f"{HLS_OUTPUT_DIR}/playlist.m3u8", f"{HLS_OUTPUT_DIR}/index.m3u8"])
                                subprocess.run(["sudo", "ln", "-sf", f"{HLS_OUTPUT_DIR}/playlist.m3u8", f"{HLS_OUTPUT_DIR}/stream.m3u8"])
                            except Exception:
                                pass
                            
                            break
                        else:
                            stderr = self.streaming_process.communicate()[1]
                            logger.error(f"Định dạng {video_format} không hoạt động: {stderr.decode()}")
                            self.streaming_process = None
                else:
                    # Thử với video/x-raw nếu đang sử dụng thiết bị thật
                    command = [
                        "sudo", "gst-launch-1.0",
                        "v4l2src", f"device={self.video_device}", "!", 
                        f"video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1", "!",
                        "videoconvert", "!",
                        "x264enc", "tune=zerolatency", "bitrate=2048", "speed-preset=ultrafast", 
                        "key-int-max=15", "!",
                        "mpegtsmux", "!",
                        "hlssink", 
                        f"location={HLS_OUTPUT_DIR}/segment%05d.ts", 
                        f"playlist-location={HLS_OUTPUT_DIR}/playlist.m3u8",
                        "target-duration=1", 
                        "max-files=15"
                    ]
                    
                    logger.info("Sử dụng lệnh: " + " ".join(command))
                    
                    self.streaming_process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    time.sleep(3)
                
                # Kiểm tra lần cuối
                if self.streaming_process is None or self.streaming_process.poll() is not None:
                    stderr = self.streaming_process.communicate()[1] if self.streaming_process else b""
                    logger.error(f"Tất cả các định dạng đều thất bại: {stderr.decode()}")
                    
                    # Cuối cùng, thử phương pháp RTP/UDP thay vì HLS
                    logger.info("Thử dùng RTP/UDP thay vì HLS...")
                    
                    if self.is_virtual_device:
                        command = [
                            "sudo", "gst-launch-1.0",
                            "v4l2src", f"device={self.video_device}", "!", 
                            f"video/x-raw,width={self.width},height={self.height}", "!",
                            "videoconvert", "!",
                            "x264enc", "tune=zerolatency", "bitrate=2048", "!",
                            "rtph264pay", "!", "udpsink", f"host={self.ip_address}", "port=5000"
                        ]
                    else:
                        command = [
                            "sudo", "gst-launch-1.0",
                            "v4l2src", f"device={self.video_device}", "!", 
                            f"image/jpeg,width={self.width},height={self.height}", "!",
                            "jpegdec", "!", "videoconvert", "!",
                            "x264enc", "tune=zerolatency", "bitrate=2048", "!",
                            "rtph264pay", "!", "udpsink", f"host={self.ip_address}", "port=5000"
                        ]
                        
                    logger.info("Sử dụng lệnh RTP: " + " ".join(command))
                    
                    self.streaming_process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    time.sleep(3)
                    
                    if self.streaming_process.poll() is None:
                        logger.info(f"Đang phát qua RTP, có thể xem qua VLC với: rtp://@{self.ip_address}:5000")
                    else:
                        logger.error("Không thể phát qua RTP")
                        return False
            
            # Tạo symbolic link để các trình phát dễ tìm file m3u8
            try:
                subprocess.run(["sudo", "ln", "-sf", f"{HLS_OUTPUT_DIR}/playlist.m3u8", f"{HLS_OUTPUT_DIR}/index.m3u8"])
                subprocess.run(["sudo", "ln", "-sf", f"{HLS_OUTPUT_DIR}/playlist.m3u8", f"{HLS_OUTPUT_DIR}/stream.m3u8"])
            except Exception:
                pass
            
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
            
            # Hiển thị các hướng dẫn kết nối cho người dùng
            stream_url = f"http://{self.ip_address}/playlist.m3u8"
            
            logger.info(f"Streaming HLS đã bắt đầu thành công:")
            logger.info(f"- Stream URL (cho VLC): {stream_url}")
            logger.info("Các lưu ý quan trọng để xem video trên VLC:")
            logger.info("1. Trên VLC: Media > Open Network Stream > nhập URL stream")
            logger.info("2. Đảm bảo máy client kết nối cùng mạng với Raspberry Pi")
            logger.info("3. Nếu stream bị lag, hãy vào VLC > Tools > Preferences > Input & Codecs > Network caching và đặt giá trị 1000ms")
            logger.info(f"4. Bạn cũng có thể thử các URL thay thế: http://{self.ip_address}/index.m3u8 hoặc http://{self.ip_address}/stream.m3u8")
            
            # Để tạo thuận lợi cho việc kiểm tra, hãy thử curl để xem nội dung playlist
            try:
                check_playlist = subprocess.run(["cat", f"{HLS_OUTPUT_DIR}/playlist.m3u8"], capture_output=True, text=True)
                logger.info(f"Nội dung của playlist.m3u8:\n{check_playlist.stdout}")
            except Exception:
                pass
            
            self.running = True
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu streaming HLS: {str(e)}")
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
    
    # Lệnh GStreamer để streaming - sử dụng định dạng JPEG chính xác như yêu cầu
    command = [
        "sudo", "gst-launch-1.0",
        "v4l2src", f"device={physical_device}", "!", 
        f"image/jpeg,width={width},height={height},framerate={framerate}/1", "!",
        "jpegdec", "!",
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