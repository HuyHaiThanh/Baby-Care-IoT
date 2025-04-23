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
    print("Status display will start in 3 seconds...")
    time.sleep(3)  # Give time to read initial info
    
    # Update interval
    update_interval = 1.0
    
    # Function to get status information
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
        status_lines.append(f"[{current_time}] Status: Audio:{AUDIO_SERVER_HOST} | Image:{IMAGE_SERVER_HOST}:{IMAGE_SERVER_PORT}")
        
        # WebSocket information
        ws_line = "• WebSocket: "
        if audio_client:
            audio_ws = "✓" if audio_client.ws_connected else "✗"
            ws_line += f"Audio[{audio_ws}] "
        if camera_client:
            camera_ws = "✓" if camera_client.ws_connected else "✗" 
            ws_line += f"Image[{camera_ws}]"
        status_lines.append(ws_line)
        
        # Audio information
        if audio_client:
            audio_status = "Recording" if audio_client.is_recording else "Paused"
            current_file = f"audio_chunk_{audio_client.save_counter}"
            status_lines.append(f"• Audio: {audio_status}")
            status_lines.append(f"  - File: {current_file}")
            status_lines.append(f"  - Status: {audio_client.last_ws_status}")
            status_lines.append(f"  - Process time: ~{audio_client.window_size*0.8:.1f}s | Send time: ~{audio_client.window_size/10:.1f}s")
            status_lines.append(f"  - Processed: {audio_client.save_counter} samples")
            
            # Queue information
            queue_size = audio_client.chunk_queue.qsize() if hasattr(audio_client.chunk_queue, 'qsize') else 0
            status_lines.append(f"  - Sent: {audio_client.save_counter} | Queue: {queue_size} chunks")
            status_lines.append(f"  - Window: {audio_client.window_size}s | Slide: {audio_client.slide_size}s | {audio_client.sample_rate} Hz, {audio_client.channels}ch")
        
        # Camera information
        if camera_client:
            capture_time = f"{camera_client.capture_duration:.1f}s"
            sending_time = f"{camera_client.sending_duration:.1f}s"
            
            status_lines.append(f"• Images: Every {args.photo_interval}s")
            status_lines.append(f"  - File: {camera_client.current_photo_file}")
            status_lines.append(f"  - Status: {camera_client.processing_status}")
            status_lines.append(f"  - Capture: {capture_time} | Send: {sending_time}")
            status_lines.append(f"  - Resolution: 640x480px")
            status_lines.append(f"  - Captured: {camera_client.total_photos_taken} | Sent: {camera_client.sent_success_count} | Queue: {camera_client.sent_fail_count}")
        
        return status_lines
    
    # Check if we're in a terminal that supports ANSI escape codes
    if sys.stdout.isatty() and not args.debug:
        # Use ANSI escape codes for clearing screen and cursor positioning
        CLEAR_SCREEN = "\033[2J\033[1;1H"  # Clear entire screen and move cursor to top-left
        
        # Main display loop
        try:
            while running:
                status_lines = get_status_display()
                # Clear screen and print updated status
                print(CLEAR_SCREEN, end='')
                print("\n".join(status_lines))
                time.sleep(update_interval)
                
        except KeyboardInterrupt:
            logger.info("Stop signal received from user")
    else:
        # Fall back to static display for non-terminal or debug mode
        print("\nRunning in static display mode (debug or non-terminal).")
        print("Status information will be logged but not continuously displayed.")
        
        try:
            # Print status once and then just wait
            status_lines = get_status_display()
            print("\n".join(status_lines))
            
            while running:
                time.sleep(update_interval)
                if args.debug:
                    # In debug mode, periodically print just a simple status line
                    runtime = time.time() - start_time
                    mins, secs = divmod(int(runtime), 60)
                    print(f"[{mins:02d}:{secs:02d}] Running: A:{audio_client.save_counter if audio_client else 'N/A'} | C:{camera_client.total_photos_taken if camera_client else 'N/A'}")
                
        except KeyboardInterrupt:
            logger.info("Stop signal received from user")
    
    # Cleanup on exit
    print("\nStopping system...")
    
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

if __name__ == "__main__":
    main()