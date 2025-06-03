# File: src/clients/camera_client.py
# Module for capturing and sending images to server

import os
import time
import datetime
import threading
import subprocess
import re
import base64
import json
import queue
from io import BytesIO

from ..core.config import (
    PHOTO_DIR, TEMP_DIR, DEVICE_ID, IMAGE_WS_ENDPOINT, 
    PHOTO_INTERVAL, get_ws_url
)
from ..utils import get_timestamp, logger
from ..network import WebSocketClient
from .base_client import BaseClient

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


class CameraClient(BaseClient):
    """
    Client for capturing and sending images to the server
    """
    def __init__(self, interval=1, max_queue_size=5, camera_device=None):
        """
        Initialize camera client
        
        Args:
            interval (int): Time interval between image captures (seconds)
            max_queue_size (int): Maximum number of images in the queue (default 5)
            camera_device (str): Specific camera device path (e.g., '/dev/video17')
        """
        super().__init__(client_type="camera", device_id=DEVICE_ID)
        
        self.interval = interval
        self.photo_thread = None
        self.max_queue_size = max_queue_size
        self.image_queue = queue.Queue(maxsize=max_queue_size)
        self.dropped_images_count = 0
        self.sending_in_progress = False
        self.queue_size_counter = 0
        self.camera_device = camera_device
        
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
        
        # Create required directories
        os.makedirs(PHOTO_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)

    def start(self):
        """
        Start camera client
        """
        self.running = True
        
        # Get the most up-to-date WebSocket URL
        base_ws_url = get_ws_url('image')
        ws_url = f"{base_ws_url}/{DEVICE_ID}"
        logger.info(f"Connecting to image WebSocket at {ws_url}")
        
        # Create WebSocket client with the updated URL
        self._create_websocket_client(ws_url)
        
        # Start WebSocket connection
        self._start_websocket()
        
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
        self._stop_websocket()
            
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
        # If specified camera device exists, use it
        if self.camera_device:
            logger.info(f"Using specified camera device: {self.camera_device}")
            if os.path.exists(self.camera_device):
                return {
                    'device': self.camera_device,
                    'index': self.camera_device.split('video')[-1] if 'video' in self.camera_device else '0',
                    'name': f"Specified device {self.camera_device}"
                }
            else:
                logger.warning(f"Specified camera device {self.camera_device} does not exist, falling back to auto-detection")
        
        devices = self.detect_video_devices()
        
        if not devices:
            return None
        
        # Always prioritize /dev/video0 if available
        for device in devices:
            if device['device'] == '/dev/video0':
                logger.info("Found physical camera device: /dev/video0")
                return device
            
        # Filter out virtual v4l2loopback devices
        physical_devices = []
        for device in devices:
            try:
                # Use v4l2-ctl to check device info
                proc = subprocess.run(
                    ['v4l2-ctl', '--device', device['device'], '--info'], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                device_info = proc.stdout.decode().lower()
                
                # Skip virtual devices
                if 'loopback' in device_info or 'virtual' in device_info:
                    logger.info(f"Skipping virtual device: {device['device']}")
                    continue
                
                physical_devices.append(device)
                
            except Exception:
                # If can't check, still add to list
                physical_devices.append(device)
        
        # Return device with lowest index if physical devices exist
        if physical_devices:
            best_device = min(physical_devices, key=lambda x: int(x['index']))
            logger.info(f"Selected camera device: {best_device['device']} ({best_device['name']})")
            return best_device
        
        # No physical devices found
        logger.warning("No suitable camera device found")
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

    def capture_photo(self):
        """
        Capture image from camera and save to specified directory
        
        Returns:
            str: Path to captured image, or None if failed
        """
        # Create directory if it doesn't exist
        os.makedirs(PHOTO_DIR, exist_ok=True)
        
        # Create filename with timestamp
        string_timestamp, _ = get_timestamp()
        filename = f"photo_{string_timestamp}.jpg"
        filepath = os.path.join(PHOTO_DIR, filename)
        
        # Try USB camera first (fswebcam)
        logger.info("Trying to capture image with fswebcam (USB camera)...")
        result = self._capture_with_fswebcam(filepath)
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
        if not self.ws_connected:
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
        
        # Create timestamp
        timestamp = time.time()
        
        try:
            # Check if queue is full, remove oldest if necessary
            if self.queue_size_counter >= self.max_queue_size:
                try:
                    # Remove oldest image
                    oldest_image_path, _ = self.image_queue.get(block=False)
                    self.queue_size_counter -= 1
                    self.image_queue.task_done()
                    logger.warning(f"Image queue full: Removed oldest image to make room for new one: {os.path.basename(oldest_image_path)}")
                except queue.Empty:
                    pass
                
            # Add new image to queue
            self.image_queue.put((image_path, timestamp), block=False)
            self.queue_size_counter += 1
            
            logger.info(f"Added image to queue. Current queue size: {self.queue_size_counter}/{self.max_queue_size}")
            
            # Start send thread if not already running
            if not self.sending_in_progress:
                send_thread = threading.Thread(target=self._send_queue_images)
                send_thread.daemon = True
                send_thread.start()
                logger.info("Starting new send thread")
            else:
                logger.info("Send thread already running, not starting a new one")
            
            self.processing_status = "Image queued for sending"
            self.next_photo_time = time.time() + self.interval
            return True
            
        except queue.Full:
            # Handle rare case where queue is still full after removal
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
        self.sending_in_progress = True
        try:
            if not self.ws_connected:
                logger.warning("No WebSocket connection, cannot send image")
                self.sending_in_progress = False
                return
            
            # Set delay between sends
            send_delay = 0.5  # Wait 500ms between image sends
                
            while not self.image_queue.empty():
                try:
                    # Get image from queue with timeout
                    image_path, timestamp = self.image_queue.get(timeout=0.5)
                    
                    # Update status and start send timing
                    self.processing_status = f"Sending image: {os.path.basename(image_path)}..."
                    send_start_time = time.time()
                    
                    # Log queue size before sending
                    logger.info(f"Sending image from queue. Queue size before: {self.queue_size_counter}")
                    
                    # Send via WebSocket
                    success = self.send_image_via_websocket(image_path, timestamp)
                    
                    # Decrease counter when image is taken from queue
                    self.queue_size_counter -= 1
                    
                    # Log queue size after sending
                    logger.info(f"Image sent. Queue size after: {self.queue_size_counter}")
                    
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
                    
                    # Brief pause between sends to reduce system load
                    time.sleep(send_delay)
                    
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"Error sending image from queue: {e}")
                    self.processing_status = f"Queue send error: {e}"
                    # Still decrease counter if error occurs
                    self.queue_size_counter = max(0, self.queue_size_counter - 1)
                    
                    # Mark task as complete even if there was an error
                    try:
                        self.image_queue.task_done()
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error in image sending thread: {e}")
        finally:
            # Always reset flag when finished
            self.sending_in_progress = False
            logger.info("Send thread finished")


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
