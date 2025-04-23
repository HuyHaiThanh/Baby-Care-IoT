# File: main.py
# Main file for running the Baby Monitoring Raspberry Pi client

import os
import time
import signal
import sys
import argparse
import traceback

# Redirect ALSA errors (run before importing audio libraries)
# Save stderr to restore later if needed
os.environ['PYTHONUNBUFFERED'] = '1'  # Ensure output is not buffered
devnull = os.open(os.devnull, os.O_WRONLY)
old_stderr = os.dup(2)
sys.stderr.flush()
os.dup2(devnull, 2)
os.close(devnull)

# Check and handle NumPy/SciPy errors
try:
    # Temporarily restore stderr to see NumPy/SciPy errors if any
    os.dup2(old_stderr, 2)
    import numpy as np
    try:
        import scipy.signal
        # Redirect stderr again after successful import
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except ImportError:
        print("\n❌ Error: NumPy and SciPy versions are incompatible!")
        print("Please reinstall the libraries with compatible versions:")
        print("\nsudo pip uninstall -y numpy scipy")
        print("sudo apt-get update")
        print("sudo apt-get install -y python3-numpy python3-scipy")
        print("\nOr if you need specific versions via pip:")
        print("pip install numpy==1.16.6 scipy==1.2.3\n")
        sys.exit(1)
except ImportError:
    print("\n❌ Error: Cannot import NumPy!")
    print("Please install NumPy with:")
    print("\nsudo apt-get update")
    print("sudo apt-get install -y python3-numpy libatlas-base-dev\n")
    sys.exit(1)

from audio_client import AudioRecorder
from camera_client import CameraClient
from utils import logger

# Flag to control program exit
running = True

def signal_handler(sig, frame):
    """Handle system shutdown signals."""
    global running
    print("\nStopping system...")
    running = False

def parse_arguments():
    """Process command line arguments"""
    parser = argparse.ArgumentParser(description='Raspberry Pi client for baby monitoring system')
    
    parser.add_argument('--no-audio', action='store_true', help='Disable audio recording')
    parser.add_argument('--no-camera', action='store_true', help='Disable camera')
    parser.add_argument('--photo-interval', type=int, default=1, help='Interval between photos (seconds)')  # Changed default to 1 second
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    return parser.parse_args()

def main():
    """Main function to start the program"""
    # Register signal handlers for program termination
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Process command line arguments
    args = parse_arguments()
    
    # System start time
    start_time = time.time()
    
    # Print startup information
    print("\n" + "=" * 60)
    print("BABY MONITORING SYSTEM - Raspberry Pi Client")
    print("=" * 60)
    
    # Initialize clients
    audio_client = None
    camera_client = None
    
    # Start AudioRecorder if not disabled via parameters
    if not args.no_audio:
        print("\n>> Starting audio processing module...")
        try:
            audio_client = AudioRecorder()
            audio_client.start_recording()
            print("✓ Audio module started successfully")
        except Exception as e:
            print(f"✗ Cannot start audio module: {e}")
            if args.debug:
                print("Detailed error:")
                traceback.print_exc()
            audio_client = None
    
    # Start CameraClient if not disabled via parameters
    if not args.no_camera:
        print("\n>> Starting image processing module...")
        try:
            camera_client = CameraClient(interval=args.photo_interval)
            if not camera_client.start():
                print("✗ Camera client start() returned False")
                camera_client = None
            else:
                print("✓ Image module started successfully")
        except Exception as e:
            print(f"✗ Cannot start image module: {e}")
            if args.debug:
                print("Detailed error:")
                traceback.print_exc()
            camera_client = None
    
    if not audio_client and not camera_client:
        print("\n❌ Error: Cannot start any module. Program will exit.")
        return
    
    # Print initial information about running modules
    print("\n" + "-" * 60)
    print("System Information:")
    print(f"• Audio mode: {'Running' if audio_client else 'Disabled'}")
    print(f"• Camera mode: {'Running' if camera_client else 'Disabled'}")
    print(f"• Connection method: WebSocket")
    
    # Display server information
    from config import AUDIO_SERVER_HOST, AUDIO_SERVER_PORT, IMAGE_SERVER_HOST, IMAGE_SERVER_PORT
    print(f"• Audio server: {AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}")
    print(f"• Image server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
    
    if camera_client:
        print(f"• Capture photos: every {args.photo_interval} seconds")
    
    print("-" * 60)
    print("\nSystem running. Press Ctrl+C to stop.")
    print("Status display will start in 2 seconds...")
    time.sleep(2)  # Give time to read initial info
    
    # Update interval
    update_interval = 1.0
    
    # Function to get status information with improved display format
    def get_status_display():
        runtime = time.time() - start_time
        hours, remainder = divmod(int(runtime), 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        current_time = time.strftime("%H:%M:%S", time.localtime())
        
        status_lines = []
        status_lines.append("=" * 60)
        status_lines.append(f"BABY MONITORING SYSTEM - Runtime: {runtime_str}")
        status_lines.append("=" * 60)
        
        # Connection status lines - one per server
        audio_ws_status = "Connected" if audio_client and audio_client.ws_connected else "Connecting..."
        status_lines.append(f"• Audio Server: {AUDIO_SERVER_HOST} | Status: {audio_ws_status}")
        
        image_ws_status = "Connected" if camera_client and camera_client.ws_connected else "Connecting..."
        status_lines.append(f"• Image Server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT} | Status: {image_ws_status}")
        
        # Audio information
        if audio_client:
            # Improve status display
            audio_status = "Recording" if audio_client.is_recording else "Paused"
            status_lines.append(f"• Audio: Every 1s")
            status_lines.append(f"  Status: {audio_status}")
            status_lines.append(f"  File: audio_chunk_{audio_client.save_counter}")
            status_lines.append(f"  - Process time: ~{audio_client.window_size*0.8:.1f}s | Send time: ~{audio_client.window_size/10:.1f}s")
            
            # Queue information - only show successfully processed items, not sent
            queue_size = audio_client.chunk_queue.qsize() if hasattr(audio_client.chunk_queue, 'qsize') else 0
            processed = audio_client.save_counter
            sent = 0  # Resetting sent count because we're not actually connected
            if audio_client.ws_connected:
                sent = processed  # Only consider items sent if we're connected
            status_lines.append(f"  - Processed: {processed} | Sent: {sent} | Queue: {queue_size}")
            status_lines.append(f"  - Window: {audio_client.window_size}s | Slide: {audio_client.slide_size}s | {audio_client.sample_rate} Hz, {audio_client.channels}ch")
        
        # Camera information
        if camera_client:
            capture_time = f"{camera_client.capture_duration:.1f}s"
            sending_time = f"{camera_client.sending_duration:.1f}s"
            
            status_lines.append(f"• Images: Every {args.photo_interval}s")
            status_lines.append(f"  - Status: {camera_client.processing_status}")
            status_lines.append(f"  File: {camera_client.current_photo_file}")
            status_lines.append(f"  Resolution: 640x480px")
            status_lines.append(f"  - Capture: {capture_time} | Send: {sending_time}")
            
            # Only count as sent if we're actually connected
            sent_count = 0
            if camera_client.ws_connected:
                sent_count = camera_client.sent_success_count
            
            status_lines.append(f"  - Captured: {camera_client.total_photos_taken} | Sent: {sent_count} | Queue: {camera_client.sent_fail_count}")
        
        return status_lines
    
    # Try to use alternative display method that works better in all terminals
    try:
        # First clear any existing output and disable cursor
        print("\033[2J\033[H\033[?25l", end="", flush=True)  # Clear screen, home cursor, hide cursor
        
        previous_output = ""
        
        # Main display loop
        while running:
            try:
                # Get current status
                status_lines = get_status_display()
                current_output = "\n".join(status_lines)
                
                # Only update if something changed
                if current_output != previous_output:
                    # Move cursor to home position
                    print("\033[H", end="", flush=True)
                    
                    # Print new status
                    print(current_output, end="", flush=True)
                    
                    # Clear to end of screen to remove any previous content
                    print("\033[J", end="", flush=True)
                    
                    # Remember output
                    previous_output = current_output
                
                # Wait for next update
                time.sleep(update_interval)
            except Exception as e:
                # If we encounter an error with this display method, fall back
                logger.error(f"Display error: {e}")
                break
                
    except KeyboardInterrupt:
        logger.info("Stop signal received from user")
    finally:
        # Show cursor again
        print("\033[?25h", end="", flush=True)
    
    # Cleanup on exit
    print("\n\nStopping system...")
    
    if audio_client:
        print(">> Stopping audio module...")
        audio_client.stop_recording()
        audio_client.close()
        
    if camera_client:
        print(">> Stopping image module...")
        camera_client.stop()
        
    # Show final status
    print("\nFinal system status:")
    final_status = get_status_display()
    print("\n".join(final_status))
    print("\n✓ System stopped safely")
    
    # Ensure we exit properly
    return 0

if __name__ == "__main__":
    main()