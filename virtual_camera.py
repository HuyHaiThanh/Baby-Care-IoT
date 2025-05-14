#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import threading
import logging
import re

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('virtual_camera')

def find_available_camera_devices():
    """Tìm tất cả các thiết bị camera vật lý có sẵn"""
    available_devices = []
    try:
        # Liệt kê các thiết bị video
        result = subprocess.run(["v4l2-ctl", "--list-devices"], 
                             capture_output=True, text=True)
        
        if result.returncode == 0:
            # Tách thông tin thành các khối thiết bị
            device_blocks = result.stdout.split("\n\n")
            
            for block in device_blocks:
                if not block.strip():
                    continue
                
                # Tìm các đường dẫn thiết bị
                device_paths = re.findall(r'(/dev/video\d+)', block)
                
                for device in device_paths:
                    # Kiểm tra kỹ hơn để xác định đây có phải là thiết bị capture có thể sử dụng được không
                    try:
                        # Kiểm tra bằng ffmpeg xem có đọc được từ thiết bị không
                        check_cmd = [
                            "ffmpeg", "-f", "v4l2", "-list_formats", "all", 
                            "-i", device, "-hide_banner"
                        ]
                        check_process = subprocess.run(
                            check_cmd, 
                            capture_output=True, 
                            text=True,
                            timeout=1  # Giới hạn thời gian chờ
                        )
                        
                        # Nếu có các định dạng pixel được liệt kê, thiết bị có thể capture được
                        if "Pixel format" in check_process.stderr and "Input/output error" not in check_process.stderr:
                            logger.info(f"Tìm thấy thiết bị camera hoạt động: {device}")
                            available_devices.append(device)
                            # Tìm thấy thiết bị thực hoạt động, có thể dừng việc tìm kiếm
                            return [device]
                            
                    except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
                        # Thử cách khác để kiểm tra
                        try:
                            caps_check = subprocess.run(
                                ["v4l2-ctl", "--device", device, "--all"], 
                                capture_output=True, 
                                text=True,
                                timeout=1
                            )
                            
                            # Kiểm tra xem thiết bị có phải là camera thực không (không phải loopback hay ảo)
                            if ("Format Video Capture" in caps_check.stdout and 
                                "loopback" not in caps_check.stdout and
                                "Input/output error" not in caps_check.stderr):
                                
                                logger.info(f"Tìm thấy thiết bị camera: {device}")
                                available_devices.append(device)
                        except Exception:
                            pass
            
            if not available_devices:
                # Thử tìm bằng cách đơn giản hơn nếu không tìm thấy
                for i in range(10):  # Thử từ video0 đến video9
                    device = f"/dev/video{i}"
                    if os.path.exists(device):
                        try:
                            # Kiểm tra nhanh
                            probe_cmd = ["ffmpeg", "-f", "v4l2", "-hide_banner", "-t", "0.1", "-i", device, "-frames:v", "1", "-f", "null", "-"]
                            probe_result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1)
                            if probe_result.returncode == 0 or "Immediate exit requested" in probe_result.stderr.decode():
                                available_devices.append(device)
                                logger.info(f"Tìm thấy thiết bị camera hoạt động (phương pháp thay thế): {device}")
                                return [device]
                        except Exception:
                            continue
        else:
            # Nếu v4l2-ctl không hoạt động, thử tìm bằng cách kiểm tra các file thiết bị
            for i in range(10):
                device = f"/dev/video{i}"
                if os.path.exists(device):
                    try:
                        # Kiểm tra nhanh
                        probe_cmd = ["ffmpeg", "-f", "v4l2", "-hide_banner", "-t", "0.1", "-i", device, "-frames:v", "1", "-f", "null", "-"]
                        probe_result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1)
                        if probe_result.returncode == 0 or "Immediate exit requested" in probe_result.stderr.decode():
                            available_devices.append(device)
                            logger.info(f"Tìm thấy thiết bị camera hoạt động (phương pháp thay thế): {device}")
                            return [device]
                    except Exception:
                        continue
    except Exception as e:
        logger.error(f"Lỗi khi tìm thiết bị camera: {str(e)}")
    
    # Mặc định là video0 nếu có lỗi hoặc không tìm thấy thiết bị nào
    if not available_devices and os.path.exists("/dev/video0"):
        logger.warning("Không tìm thấy thiết bị camera hoạt động. Thử dùng /dev/video0 như mặc định")
        available_devices.append("/dev/video0")
    
    return available_devices

class VirtualCameraManager:
    def __init__(self, physical_device="/dev/video0", virtual_device="/dev/video10"):
        """
        Khởi tạo quản lý camera ảo
        
        Args:
            physical_device: Thiết bị camera vật lý
            virtual_device: Thiết bị camera ảo sẽ được tạo
        """
        # Tìm thiết bị camera khả dụng nếu thiết bị được chỉ định không tồn tại
        self.physical_device = physical_device
        if not os.path.exists(physical_device):
            available_cameras = find_available_camera_devices()
            if available_cameras:
                self.physical_device = available_cameras[0]
                logger.info(f"Thiết bị camera vật lý được chỉ định không tồn tại. Chuyển sang thiết bị: {self.physical_device}")
            else:
                logger.warning(f"Không tìm thấy thiết bị camera nào khả dụng. Vẫn giữ nguyên thiết bị: {self.physical_device}")
        
        self.virtual_device = virtual_device  # Thiết bị ảo mặc định
        self.v4l2_process = None
        self.copy_completed = False
        self.device_freed = False
        self.virtual_device_created = False
    
    def check_v4l2loopback_installed(self):
        """Kiểm tra xem v4l2loopback đã được cài đặt chưa"""
        try:
            # Kiểm tra xem module có sẵn sàng để nạp không
            check_available = subprocess.run(["modinfo", "v4l2loopback"], 
                                          capture_output=True, text=True)
            if check_available.returncode == 0:
                return True
                
            # Nếu không có sẵn, kiểm tra xem gói có được cài đặt không
            check_installed = subprocess.run(["dpkg", "-s", "v4l2loopback-dkms"], 
                                         capture_output=True, text=True)
            if check_installed.returncode == 0:
                return True
                
            # Cố gắng cài đặt
            logger.warning("v4l2loopback chưa được cài đặt. Cố gắng cài đặt...")
            subprocess.run(["sudo", "apt-get", "update", "-y"], capture_output=True)
            install_result = subprocess.run(["sudo", "apt-get", "install", "-y", "v4l2loopback-dkms", "v4l2loopback-utils"], 
                                         capture_output=True, text=True)
            
            if install_result.returncode == 0:
                logger.info("Đã cài đặt v4l2loopback thành công")
                return True
            else:
                logger.error(f"Không thể cài đặt v4l2loopback: {install_result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra v4l2loopback: {str(e)}")
            return False
    
    def find_available_video_device(self):
        """Tìm một số thiết bị virtual video khả dụng"""
        for i in range(10, 30):  # Thử từ video10 đến video29
            device_path = f"/dev/video{i}"
            if not os.path.exists(device_path):
                return device_path, i
        return "/dev/video10", 10  # Mặc định nếu không tìm thấy
    
    def cleanup_existing_devices(self):
        """Dọn dẹp các thiết bị video ảo đang tồn tại"""
        try:
            # Tắt module v4l2loopback nếu đang chạy
            logger.info("Đang dọn dẹp các thiết bị video ảo hiện có...")
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], 
                          capture_output=True, text=True)
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Lỗi khi dọn dẹp thiết bị ảo: {str(e)}")
            return False
            
    def setup_virtual_camera(self):
        """
        Thiết lập v4l2loopback để tạo thiết bị camera ảo
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        try:
            # Kiểm tra xem v4l2loopback đã được cài đặt chưa
            if not self.check_v4l2loopback_installed():
                logger.error("v4l2loopback không được cài đặt. Không thể tạo thiết bị camera ảo.")
                return False
            
            # Dọn dẹp các thiết bị cũ trước
            self.cleanup_existing_devices()
                        
            # Tìm một thiết bị khả dụng
            self.virtual_device, device_number = self.find_available_video_device()
            logger.info(f"Sử dụng thiết bị ảo: {self.virtual_device}")
            
            # Nạp module v4l2loopback với các tùy chọn đơn giản hơn cho Raspberry Pi 2B
            logger.info("Đang nạp module v4l2loopback...")
            # Sử dụng syntax đơn giản hơn cho Raspberry Pi 2B
            cmd = [
                "sudo", "modprobe", "v4l2loopback",
                f"video_nr={device_number}",
                "exclusive_caps=0",
                "card_label=VirtualCam"  # Không sử dụng dấu nháy kép để tránh sự cố
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Không thể nạp module v4l2loopback: {result.stderr}")
                # Thử cách khác với ít tham số hơn
                simple_cmd = ["sudo", "modprobe", "v4l2loopback"]
                simple_result = subprocess.run(simple_cmd, capture_output=True, text=True)
                if simple_result.returncode != 0:
                    logger.error(f"Không thể nạp module v4l2loopback đơn giản: {simple_result.stderr}")
                    return False
                logger.info("Đã nạp module v4l2loopback thành công với cách đơn giản")
                
            time.sleep(3)  # Đợi module được nạp
            
            # Kiểm tra xem thiết bị đã được tạo chưa
            if os.path.exists(self.virtual_device):
                self.virtual_device_created = True
                logger.info(f"Thiết bị ảo {self.virtual_device} đã được tạo thành công")
                return True
            else:
                # Nếu thiết bị không tồn tại, thử tìm một thiết bị khác đã được tạo
                logger.warning(f"Thiết bị ảo {self.virtual_device} không tồn tại. Đang tìm thiết bị v4l2loopback khác...")
                
                # Thử kiểm tra tất cả các thiết bị video từ 0-20
                for i in range(20):
                    test_device = f"/dev/video{i}"
                    if os.path.exists(test_device):
                        try:
                            # Kiểm tra xem thiết bị có phải là v4l2loopback không
                            device_info = subprocess.run(["v4l2-ctl", "-d", test_device, "--info"], 
                                                    capture_output=True, text=True, timeout=2)
                            
                            if "v4l2loopback" in device_info.stdout or "loopback" in device_info.stdout:
                                self.virtual_device = test_device
                                self.virtual_device_created = True
                                logger.info(f"Tìm thấy thiết bị v4l2loopback: {test_device}")
                                return True
                        except Exception:
                            continue
            
            logger.error("Không tìm thấy thiết bị v4l2loopback nào")
            return False
            
        except Exception as e:
            logger.error(f"Lỗi khi thiết lập v4l2loopback: {str(e)}")
            return False
    
    def free_physical_device(self):
        """
        Giải phóng thiết bị camera vật lý để các tiến trình khác có thể sử dụng
        """
        if self.copy_completed and not self.device_freed:
            logger.info(f"Đang giải phóng thiết bị vật lý {self.physical_device}...")
            
            if self.v4l2_process:
                logger.info("Dừng tiến trình sao chép video để giải phóng thiết bị vật lý")
                self.v4l2_process.terminate()
                try:
                    self.v4l2_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.v4l2_process.kill()
                self.v4l2_process = None
            
            # Giải phóng thiết bị vật lý nếu có tiến trình nào đang sử dụng
            try:
                check_busy = subprocess.run(["fuser", "-v", self.physical_device], 
                                          capture_output=True, text=True)
                
                if check_busy.returncode == 0:  # Có tiến trình đang sử dụng
                    subprocess.run(["sudo", "fuser", "-k", self.physical_device], 
                                 capture_output=True, text=True)
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Lỗi khi giải phóng thiết bị: {str(e)}")
            
            self.device_freed = True
            logger.info(f"Thiết bị vật lý {self.physical_device} đã được giải phóng")
    
    def start_video_copying(self):
        """
        Bắt đầu sao chép luồng video từ thiết bị thật sang thiết bị ảo
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        if not self.virtual_device_created:
            logger.warning("Không thể sao chép video vì thiết bị ảo không tồn tại")
            return False
            
        if self.v4l2_process:
            return True
            
        logger.info(f"Bắt đầu sao chép video từ {self.physical_device} sang {self.virtual_device}")
        
        try:
            # Kiểm tra xem có tiến trình nào đang sử dụng camera không
            try:
                check_busy = subprocess.run(["fuser", "-v", self.physical_device], 
                                        capture_output=True, text=True)
                
                if check_busy.returncode == 0:  # Có tiến trình đang sử dụng
                    logger.warning(f"Camera {self.physical_device} đang được sử dụng bởi tiến trình khác. Thử giải phóng...")
                    subprocess.run(["sudo", "fuser", "-k", self.physical_device], 
                                capture_output=True, text=True)
                    time.sleep(2)  # Đợi giải phóng thiết bị
            except Exception:
                pass  # Bỏ qua nếu không có công cụ fuser
            
            # Sử dụng ffmpeg để sao chép từ camera thực sang thiết bị ảo
            # Tránh chỉ định input_format để ffmpeg tự phát hiện định dạng tốt nhất
            command = [
                "ffmpeg", 
                "-f", "v4l2", 
                "-i", self.physical_device,
                "-vcodec", "copy",  # Sao chép mã hóa để giữ chất lượng và hiệu suất
                "-f", "v4l2", 
                self.virtual_device
            ]
            
            logger.info("Sử dụng lệnh sao chép: " + " ".join(command))
            
            self.v4l2_process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(3)  # Đợi để ffmpeg thiết lập đầy đủ
            
            if self.v4l2_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Không thể sao chép video: {stderr.decode()}")
                self.v4l2_process = None
                
                # Thử phương pháp sao chép thay thế
                return self.start_video_copying_alternative()
            
            # Thiết lập cờ copy_completed
            self.copy_completed = True
            # Chạy một thread để giải phóng thiết bị vật lý sau 5 giây
            threading.Timer(5.0, self.free_physical_device).start()
                
            logger.info("Video đang được sao chép thành công")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi bắt đầu sao chép video: {str(e)}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False

    def start_video_copying_alternative(self):
        """
        Phương pháp thay thế để sao chép video sang thiết bị ảo
        
        Returns:
            bool: True nếu thành công, False nếu thất bại
        """
        logger.info("Thử phương pháp thay thế để sao chép video...")
        
        try:
            # Sử dụng GStreamer thay vì ffmpeg
            command = [
                "gst-launch-1.0", "-v",
                f"v4l2src device={self.physical_device} ! videoconvert ! v4l2sink device={self.virtual_device}"
            ]
            
            self.v4l2_process = subprocess.Popen(
                " ".join(command),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            time.sleep(3)
            
            if self.v4l2_process.poll() is not None:
                # Nếu process đã kết thúc, có lỗi
                stdout, stderr = self.v4l2_process.communicate()
                logger.error(f"Phương pháp sao chép thay thế cũng thất bại: {stderr.decode()}")
                self.v4l2_process = None
                return False
            
            self.copy_completed = True
            threading.Timer(5.0, self.free_physical_device).start()
            
            logger.info("Video đang được sao chép thành công với phương pháp thay thế")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi sử dụng phương pháp sao chép thay thế: {str(e)}")
            if self.v4l2_process:
                self.v4l2_process.terminate()
                self.v4l2_process = None
            return False
    
    def stop_video_copying(self):
        """Dừng quá trình sao chép video"""
        if self.v4l2_process:
            logger.info("Đang dừng quá trình sao chép video...")
            self.v4l2_process.terminate()
            try:
                self.v4l2_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.v4l2_process.kill()
            self.v4l2_process = None
    
    def start(self):
        """
        Khởi động quản lý camera ảo
        
        Returns:
            tuple: (bool, str) - (thành công/thất bại, thiết bị sử dụng)
        """
        # Thiết lập camera ảo
        v4l2_setup_success = self.setup_virtual_camera()
        
        # Sao chép video từ thiết bị vật lý sang thiết bị ảo
        if v4l2_setup_success:
            if self.start_video_copying():
                logger.info("Sao chép video thành công từ camera thật sang thiết bị ảo")
                return True, self.virtual_device
            else:
                logger.warning("Không thể sao chép video sang thiết bị ảo, sử dụng thiết bị gốc")
                return False, self.physical_device
        else:
            logger.warning("Không thể thiết lập thiết bị ảo, sử dụng thiết bị gốc")
            return False, self.physical_device
    
    def stop(self):
        """Dừng camera ảo và dọn dẹp tài nguyên"""
        self.stop_video_copying()
        
        # Cố gắng tắt module v4l2loopback
        try:
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], 
                          capture_output=True, text=True)
        except Exception:
            pass
        
        logger.info("Đã dừng quản lý camera ảo")

def main():
    """
    Hàm chính để kiểm tra chức năng tạo camera ảo
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Quản lý thiết bị camera ảo')
    parser.add_argument('--physical-device', help='Thiết bị camera vật lý')
    parser.add_argument('--virtual-device', help='Thiết bị camera ảo')
    parser.add_argument('--cleanup', action='store_true', help='Dọn dẹp các thiết bị ảo hiện có')
    
    args = parser.parse_args()
    
    if args.cleanup:
        # Nếu chỉ cần dọn dẹp
        try:
            subprocess.run(["sudo", "modprobe", "-r", "v4l2loopback"], 
                          capture_output=True, text=True)
            logger.info("Đã dọn dẹp các thiết bị camera ảo")
            return
        except Exception as e:
            logger.error(f"Lỗi khi dọn dẹp: {e}")
            return
    
    physical_device = args.physical_device
    if not physical_device:
        # Tự động tìm thiết bị camera nếu không được chỉ định
        devices = find_available_camera_devices()
        if devices:
            physical_device = devices[0]
            logger.info(f"Tự động phát hiện camera: {physical_device}")
        else:
            physical_device = '/dev/video0'
            logger.warning(f"Không tìm thấy camera. Sử dụng mặc định: {physical_device}")
    
    # Khởi tạo quản lý camera ảo
    manager = VirtualCameraManager(physical_device=physical_device, virtual_device=args.virtual_device)
    
    try:
        # Khởi động
        success, device = manager.start()
        
        if success:
            logger.info(f"Camera ảo đã được khởi tạo thành công. Thiết bị: {device}")
            logger.info("Nhấn Ctrl+C để dừng")
            # Giữ cho chương trình chạy
            while True:
                time.sleep(1)
        else:
            logger.info(f"Không thể khởi tạo camera ảo. Sử dụng thiết bị gốc: {device}")
    
    except KeyboardInterrupt:
        logger.info("Đã nhận ngắt từ bàn phím.")
    finally:
        # Dừng camera ảo
        manager.stop()

if __name__ == "__main__":
    main()