# File: camera_client.py
# Module for capturing and sending images to server

import os
import time
import datetime
import threading
import subprocess
import re
import base64
import json
from io import BytesIO
from config import (
    PHOTO_DIR, TEMP_DIR, DEVICE_ID, IMAGE_WS_ENDPOINT, 
    PHOTO_INTERVAL
)
from utils import get_timestamp, logger
from websocket_client import WebSocketClient

# Flag for PiCamera or USB camera availability
PICAMERA_AVAILABLE = False

try:
    from PIL import Image
    logger.info("PIL library detected")
except ImportError:
    logger.warning("WARNING: PIL library not found. Image processing capabilities will be limited.")

try:
    from picamera import PiCamera
    PICAMERA_AVAILABLE = True
    logger.info("PiCamera detected.")
except ImportError:
    logger.warning("PiCamera not found. Will use USB camera if available.")


class CameraClient:
    """
    Client for capturing and sending images to the server
    """
    def __init__(self, interval=1, max_queue_size=5):
        """
        Initialize camera client
        
        Args:
            interval (int): Time interval between image captures (seconds)
            max_queue_size (int): Maximum number of images in the queue (default 5)
        """
        self.interval = interval
        self.running = False
        self.photo_thread = None
        self.max_queue_size = max_queue_size
        self.image_queue = queue.Queue(maxsize=max_queue_size)
        self.dropped_images_count = 0
        
        # Image statistics
        self.sent_success_count = 0
        self.sent_fail_count = 0
        self.total_photos_taken = 0
        
        # Processing status tracking
        self.current_photo_file = "None"
        self.processing_status = "Waiting"
        self.next_photo_time = time.time() + interval
        
        # Timing metrics
        self.last_capture_time = time.time()
        self.last_sent_time = 0
        self.capture_duration = 0
        self.sending_duration = 0
        
        # WebSocket client
        self.ws_client = WebSocketClient(
            ws_url=IMAGE_WS_ENDPOINT,
            device_id=DEVICE_ID,
            client_type="camera"
        )
        
        # Create required directories
        os.makedirs(PHOTO_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        
    def start(self):
        """
        Start camera client
        """
        self.running = True
        
        # Start WebSocket connection
        self.ws_client.connect()
        
        # Start photo capture thread
        self.photo_thread = threading.Thread(target=self._photo_thread)
        self.photo_thread.daemon = True
        self.photo_thread.start()
            
        logger.info("Camera client started")
        return True
        
    def stop(self):
        """
        Stop camera client
        """
        self.running = False
        
        # Close WebSocket connection
        self.ws_client.close()
            
        # Wait for processing thread to finish
        if self.photo_thread and self.photo_thread.is_alive():
            self.photo_thread.join(timeout=1.0)
            
        logger.info("Camera client stopped")
    
    def _photo_thread(self):
        """
        Thread for periodically capturing images and sending to server
        """
        while self.running:
            try:
                # Capture and send image
                self.capture_and_send_photo()
                
                # Wait for next capture time
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in photo capture thread: {e}")
                time.sleep(self.interval)
    
    def detect_video_devices(self):
        """Detect and return USB camera devices"""
        try:
            # Use v4l2-ctl to list video devices
            proc = subprocess.run(['v4l2-ctl', '--list-devices'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            devices_output = proc.stdout.decode()
            
            if not devices_output.strip():
                # Try alternative method to list video devices
                proc = subprocess.run(['ls', '-la', '/dev/video*'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                devices_output = proc.stdout.decode()
                
                if 'No such file or directory' in devices_output:
                    return []
                    
                # Parse output to find video devices
                video_devices = []
                for line in devices_output.splitlines():
                    match = re.search(r'/dev/video(\d+)', line)
                    if match:
                        video_devices.append({
                            'device': match.group(0),
                            'index': match.group(1),
                            'name': f"Video Device {match.group(1)}"
                        })
                return video_devices
            
            # Parse v4l2-ctl output
            devices = []
            current_device = None
            for line in devices_output.splitlines():
                if ':' in line and '/dev/video' not in line:
                    # This is a device name
                    current_device = line.strip().rstrip(':')
                elif '/dev/video' in line:
                    # This is a device path
                    match = re.search(r'/dev/video(\d+)', line)
                    if match and current_device:
                        devices.append({
                            'device': match.group(0),
                            'index': match.group(1),
                            'name': current_device
                        })
            return devices
        except Exception as e:
            logger.error(f"Error detecting camera devices: {e}")
            return []
    
    def get_best_video_device(self):
        """Choose the most suitable camera device"""
        devices = self.detect_video_devices()
        
        if not devices:
            return None
            
        # Prefer USB cameras with camera, webcam, usb in name
        for device in devices:
            if 'camera' in device.get('name', '').lower() or 'webcam' in device.get('name', '').lower() or 'usb' in device.get('name', '').lower():
                return device
        
        # If none found, use first device
        if len(devices) > 0:
            return devices[0]
            
        return None

    def _capture_with_fswebcam(self, output_path):
        """Capture image with fswebcam (for USB cameras)"""
        try:
            # Find camera device
            device = self.get_best_video_device()
            if not device:
                logger.error("No USB camera device found")
                return None
                    
            # Use fswebcam to capture image
            device_path = device['device']
            logger.info(f"Starting image capture from device {device_path}...")
            
            # Ensure temp directory exists
            os.makedirs(TEMP_DIR, exist_ok=True)
            
            # Temporary file path
            temp_path = os.path.join(TEMP_DIR, "temp_capture.jpg")
            
            # Capture image with fswebcam at lower resolution
            subprocess.run([
                'fswebcam',
                '-q',                   # Quiet mode (no banner)
                '-r', '640x480',        # Lower resolution
                '--no-banner',          # No banner display
                '-d', device_path,      # Camera device
                '--jpeg', '70',         # Reduce JPEG quality to speed up
                '-F', '2',              # Reduce frames to skip (speed up)
                temp_path               # Output file path
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5)
            
            # Check if file was created successfully
            if not os.path.exists(temp_path):
                logger.error("Error capturing image - file not created")
                return None
                
            if os.path.getsize(temp_path) < 1000:  # Check minimum file size
                logger.error("Error capturing image - file too small, may be corrupted")
                os.remove(temp_path)
                return None
                
            # Move file from temp to destination directory
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            import shutil
            shutil.copy(temp_path, output_path)
            os.remove(temp_path)
            
            logger.info(f"Image captured: {output_path}")
            return output_path
                    
        except Exception as e:
            logger.error(f"Error capturing image with fswebcam: {e}")
            # Clean up temp file if there was an error
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return None

    def _capture_with_libcamera(self, output_path):
        """Capture image with libcamera-still (for Pi Camera)"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Use libcamera-still with lower resolution
            subprocess.run([
                'libcamera-still',
                '-t', '500',            # Reduce wait time to 0.5 seconds
                '-n',                   # No preview
                '--width', '640',       # Reduce width
                '--height', '480',      # Reduce height
                '-o', output_path       # Output file path
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=3)
            
            # Check if file was created successfully
            if not os.path.exists(output_path):
                logger.error("Error capturing image with libcamera - file not created")
                return None
                
            if os.path.getsize(output_path) < 1000:  # Check minimum file size
                logger.error("Error capturing image with libcamera - file too small, may be corrupted")
                os.remove(output_path)
                return None
                
            logger.info(f"Image captured with libcamera: {output_path}")
            return output_path
                    
        except FileNotFoundError:
            logger.warning("libcamera-still not found on system")
            return None
        except Exception as e:
            logger.error(f"Error capturing image with libcamera: {e}")
            return None

    def _capture_with_picamera(self, output_path):
        """Capture image with PiCamera module"""
        if not PICAMERA_AVAILABLE:
            logger.warning("PiCamera library not found")
            return None
            
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            camera = PiCamera()
            camera.resolution = (640, 480)  # Lower resolution
            
            # Initialize camera and wait for light balance (reduce wait time)
            camera.start_preview()
            time.sleep(0.5)  # Reduce wait time to 0.5 seconds
            
            # Capture image
            camera.capture(output_path)
            camera.stop_preview()
            camera.close()
            
            logger.info(f"Image captured with PiCamera: {output_path}")
            return output_path
        
        except Exception as e:
            logger.error(f"Error capturing image with PiCamera: {e}")
            return None

    def _capture_with_ffmpeg(self, output_path):
        """Capture image with ffmpeg (fallback method)"""
        try:
            # Find camera device
            device = self.get_best_video_device()
            if not device:
                return None
                
            device_path = device['device']
            
            subprocess.run([
                'ffmpeg',
                '-f', 'video4linux2',
                '-i', device_path,
                '-frames:v', '1',       # Capture one frame
                '-s', '640x480',        # Lower resolution
                '-y',                   # Overwrite output file
                output_path
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=3)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Image captured with ffmpeg: {output_path}")
                return output_path
            return None
        except Exception as e:
            logger.error(f"Error capturing image with ffmpeg: {e}")
            return None

    def _capture_with_v4l2_grab(self, output_path):
        """Capture image with v4l2-grab (fallback method)"""
        try:
            device = self.get_best_video_device()
            if not device:
                return None
                
            device_path = device['device']
            
            subprocess.run([
                'v4l2-grab',
                '-d', device_path,
                '-o', output_path
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=3)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Image captured with v4l2-grab: {output_path}")
                return output_path
            return None
        except Exception as e:
            logger.error(f"Error capturing image with v4l2-grab: {e}")
            return None

    def _capture_with_uvccapture(self, output_path):
        """Capture image with uvccapture (fallback method)"""
        try:
            device = self.get_best_video_device()
            if not device:
                return None
                
            device_path = device['device']
            
            subprocess.run([
                'uvccapture',
                '-d', device_path,
                '-o', output_path
            ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=3)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Image captured with uvccapture: {output_path}")
                return output_path
            return None
        except Exception as e:
            logger.error(f"Error capturing image with uvccapture: {e}")
            return None

    def capture_photo(self):
        """
        Capture image from camera and save to specified directory
        Try different methods to ensure success
        
        Returns:
            str: Path to captured image, or None if failed
        """
        # Create directory if it doesn't exist
        os.makedirs(PHOTO_DIR, exist_ok=True)
        
        # Create filename with timestamp
        string_timestamp, _ = get_timestamp()
        filename = f"photo_{string_timestamp}.jpg"
        filepath = os.path.join(PHOTO_DIR, filename)
        
        # Try different capture methods in order of preference
        
        # Try USB camera first (fswebcam)
        logger.info("Trying to capture image with fswebcam (USB camera)...")
        result = self._capture_with_fswebcam(filepath)
        if result:
            return result
        
        # If PiCamera available, try PiCamera module
        if PICAMERA_AVAILABLE:
            logger.info("Trying to capture image with PiCamera module...")
            result = self._capture_with_picamera(filepath)
            if result:
                return result
        
        # Try using libcamera-still (for newer Raspberry Pi OS)
        logger.info("Trying to capture image with libcamera-still...")
        result = self._capture_with_libcamera(filepath)
        if result:
            return result
        
        # Try fallback methods if primary methods fail
        logger.info("Primary methods failed, trying fallback methods...")
        
        # Try ffmpeg
        result = self._capture_with_ffmpeg(filepath)
        if result:
            return result
        
        # Try v4l2-grab
        result = self._capture_with_v4l2_grab(filepath)
        if result:
            return result
        
        # Try uvccapture
        result = self._capture_with_uvccapture(filepath)
        if result:
            return result
        
        logger.error("Cannot capture image: All methods failed")
        return None

    def get_image_as_base64(self, image_path):
        """
        Convert image to base64 string
        
        Args:
            image_path (str): Path to image file
            
        Returns:
            str: Base64 encoded image data
        """
        try:
            # Read file directly instead of through PIL to speed up
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error reading image file: {e}")
            return None
    
    def send_image_via_websocket(self, image_path, timestamp):
        """
        Send image via WebSocket with format required by server
        
        Args:
            image_path (str): Path to image file
            timestamp (float): Time when image was captured
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.ws_client.ws_connected:
            logger.warning("No WebSocket connection, cannot send image")
            return False
        
        try:
            # Convert image to base64
            image_base64 = self.get_image_as_base64(image_path)
            if not image_base64:
                return False
                
            # Create ISO 8601 timestamp format for server compatibility
            timestamp_str = datetime.datetime.fromtimestamp(timestamp).isoformat()
                
            # Create message in server-required format
            message = {
                'image_base64': image_base64,
                'timestamp': timestamp_str
            }
            
            # Send via WebSocket
            result = self.ws_client.send_message(message)
            if result:
                logger.info(f"Image sent via WebSocket at {timestamp_str}")
            return result
            
        except Exception as e:
            logger.error(f"Error sending image via WebSocket: {e}")
            return False
    
    def capture_and_send_photo(self):
        """
        Capture image and send to server
        
        Returns:
            bool: True if successful, False otherwise
        """
        # Update status and start timing
        self.processing_status = "Capturing image..."
        capture_start_time = time.time()
        
        # Calculate time since last capture
        capture_interval = capture_start_time - self.last_capture_time
        self.last_capture_time = capture_start_time
        
        # Capture image
        image_path = self.capture_photo()
        
        # Measure image capture time
        self.capture_duration = time.time() - capture_start_time
        
        if not image_path:
            logger.error("Cannot capture image to send to server")
            self.sent_fail_count += 1
            self.processing_status = "Image capture error"
            self.current_photo_file = "None"
            return False
            
        # Save current filename
        self.current_photo_file = os.path.basename(image_path)
        
        # Increment photo count
        self.total_photos_taken += 1
        
        # Tạo timestamp
        timestamp = time.time()
        
        try:
            # Kiểm tra nếu hàng đợi đã đầy, xóa ảnh cũ nhất để có chỗ cho ảnh mới
            if self.image_queue.full():
                try:
                    # Lấy và loại bỏ ảnh cũ nhất
                    oldest_image_path, _ = self.image_queue.get(block=False)
                    self.image_queue.task_done()
                    logger.warning(f"Image queue full: Removed oldest image to make room for new one: {os.path.basename(oldest_image_path)}")
                except queue.Empty:
                    # Trường hợp hiếm khi xảy ra - queue vừa đầy vừa trống
                    pass
                
            # Thêm ảnh mới vào hàng đợi
            self.image_queue.put((image_path, timestamp), block=False)
            
            # Bắt đầu một thread mới để gửi ảnh từ hàng đợi
            send_thread = threading.Thread(target=self._send_queue_images)
            send_thread.daemon = True
            send_thread.start()
            
            self.processing_status = "Image queued for sending"
            self.next_photo_time = time.time() + self.interval
            return True
            
        except queue.Full:
            # Xử lý trường hợp hiếm gặp khi không thể thêm vào queue dù đã xóa mục cũ
            self.dropped_images_count += 1
            logger.warning(f"Queue still full after removal: Dropping image: {self.current_photo_file}. Total dropped: {self.dropped_images_count}")
            self.processing_status = "Queue still full, image dropped"
            return False
        except Exception as e:
            logger.error(f"Error while handling image queue: {e}")
            self.processing_status = f"Queue error: {e}"
            return False

    def _send_queue_images(self):
        """
        Send images from queue via WebSocket
        """
        try:
            if not self.ws_client.ws_connected:
                logger.warning("No WebSocket connection, cannot send image")
                return
                
            while not self.image_queue.empty():
                try:
                    # Lấy ảnh từ hàng đợi với timeout để tránh blocking quá lâu
                    image_path, timestamp = self.image_queue.get(timeout=0.5)
                    
                    # Update status and start send timing
                    self.processing_status = f"Sending image: {os.path.basename(image_path)}..."
                    send_start_time = time.time()
                    
                    # Send via WebSocket
                    success = self.send_image_via_websocket(image_path, timestamp)
                    
                    # Measure sending time
                    self.sending_duration = time.time() - send_start_time
                    self.last_sent_time = time.time()
                    
                    # Update counts based on success/failure
                    if success:
                        self.sent_success_count += 1
                        self.processing_status = "Sent successfully"
                    else:
                        self.sent_fail_count += 1
                        self.processing_status = "Send error"
                    
                    # Mark task as complete
                    self.image_queue.task_done()
                    
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"Error sending image from queue: {e}")
                    self.processing_status = f"Queue send error: {e}"
                    # Mark task as complete even if there was an error
                    try:
                        self.image_queue.task_done()
                    except:
                        pass
                    
        except Exception as e:
            logger.error(f"Error in image sending thread: {e}")

    @property
    def ws_connected(self):
        """
        Property to check WebSocket connection status
        
        Returns:
            bool: True if WebSocket is connected, False otherwise
        """
        return self.ws_client.ws_connected


# Test module when run directly
if __name__ == "__main__":
    # Initialize client with 1 second interval
    camera_client = CameraClient(interval=1)
    
    # Start client
    camera_client.start()
    
    try:
        # Let WebSocket client run for a while
        logger.info("Maintaining connection and capturing images for 60 seconds...")
        time.sleep(60)
        
    except KeyboardInterrupt:
        logger.info("Stop signal received")
    finally:
        # Stop client
        camera_client.stop()
        logger.info("Test completed")