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
    parser.add_argument('--photo-interval', type=int, default=5, help='Interval between photos (seconds)')
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
    
    # Print information about running modules
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
    print("\nSystem running. Press Ctrl+C to stop.\n")
    
    # Update interval (seconds)
    # Increase refresh interval to reduce flickering
    update_interval = 1.0
    
    # Store previous display content to avoid unnecessary screen clearing
    last_display = ""
    
    # Main loop to display system status
    try:
        while running:
            # Calculate runtime
            runtime = time.time() - start_time
            hours, remainder = divmod(int(runtime), 3600)
            minutes, seconds = divmod(remainder, 60)
            runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Create new display content
            current_time = time.strftime("%H:%M:%S", time.localtime())
            
            # Create content to display
            display = []
            display.append("\n" + "=" * 60)
            display.append(f"BABY MONITORING SYSTEM - Raspberry Pi Client - Runtime: {runtime_str}")
            display.append("=" * 60)
            display.append(f"\n[{current_time}] System Status:")
            display.append(f"• Audio server: {AUDIO_SERVER_HOST}")
            display.append(f"• Image server: {IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
            
            # Add WebSocket information
            if audio_client:
                audio_ws_status = "Connected" if audio_client.ws_connected else "Connecting..."
                display.append(f"• Audio WebSocket: {audio_ws_status} | Status: {audio_client.last_ws_status}")
            
            if camera_client:
                camera_ws_status = "Connected" if camera_client.ws_connected else "Connecting..."
                display.append(f"• Image WebSocket: {camera_ws_status}")
            
            # Add audio information if audio module is running
            if audio_client:
                audio_status = "Recording" if audio_client.is_recording else "Paused"
                
                # Display AudioRecorder information
                display.append(f"• Audio: {audio_status}")
                display.append(f"  - WebSocket connection: {audio_client.last_ws_status}")
                display.append(f"  - Current chunk ID: audio_chunk_{audio_client.save_counter}")
                display.append(f"  - Processed: {audio_client.save_counter} samples")
                display.append(f"  - Window size: {audio_client.window_size}s | Slide: {audio_client.slide_size}s")
                display.append(f"  - Sample rate: {audio_client.sample_rate} Hz | Channels: {audio_client.channels}")
            
            # Add image information if camera module is running
            if camera_client:
                # Format time with 1 decimal place
                capture_time = f"{camera_client.capture_duration:.1f}s"
                sending_time = f"{camera_client.sending_duration:.1f}s"
                
                display.append(f"• Images: Capturing every {args.photo_interval}s")
                display.append(f"  - Current file: {camera_client.current_photo_file}")
                display.append(f"  - Status: {camera_client.processing_status}")
                display.append(f"  - Capture time: {capture_time} | Send time: {sending_time}")
                display.append(f"  - Captured: {camera_client.total_photos_taken} images")
                display.append(f"  - Successfully sent: {camera_client.sent_success_count} images")
            
            # Combine into a string to display
            current_display = "\n".join(display)
            
            # Only clear and update screen when content changes
            if current_display != last_display:
                # Clear screen only when necessary and not in debug mode
                if not args.debug:
                    if os.name == 'posix':  # Linux/Mac
                        os.system('clear')
                    elif os.name == 'nt':   # Windows
                        # Use cmd.exe to avoid PowerShell errors
                        os.system('cmd /c cls')
                
                # Print new content
                print(current_display)
                
                # Update displayed content
                last_display = current_display
            
            # Sleep for update interval
            time.sleep(update_interval)
            
    except KeyboardInterrupt:
        logger.info("Stop signal received from user")
    finally:
        # Stop clients
        print("\nStopping system...")
        
        if audio_client:
            print(">> Stopping audio module...")
            audio_client.stop_recording()
            audio_client.close()
            
        if camera_client:
            print(">> Stopping image module...")
            camera_client.stop()
            
        print("\n✓ System stopped safely")

if __name__ == "__main__":
    main()