# File: main.py
# Điểm vào chính cho client âm thanh

import os
import sys
import argparse
from config import SERVER_HOST, HTTP_PORT, WEBSOCKET_PORT

def run_gui():
    """Chạy giao diện đồ họa"""
    from gui import run_app
    run_app()

def run_cli(server_host=None, duration=60):
    """
    Chạy client trong chế độ command line
    
    Args:
        server_host: Địa chỉ server (nếu không có sẽ dùng từ config)
        duration: Thời gian chạy (giây), 0 = chạy vô hạn
    """
    import time
    from audio_client import AudioClient
    
    if server_host:
        import config
        config.SERVER_HOST = server_host
    
    print(f"Khởi động client âm thanh, kết nối đến {SERVER_HOST}...")
    print(f"HTTP Port: {HTTP_PORT}, WebSocket Port: {WEBSOCKET_PORT}")
    
    client = AudioClient()
    
    def on_new_audio(audio_path, is_crying):
        print(f"\n[NEW] {'Tiếng khóc' if is_crying else 'Âm thanh'} mới: {os.path.basename(audio_path)}")
        
    def on_connection_change(connected):
        print(f"Trạng thái kết nối: {'Đã kết nối' if connected else 'Mất kết nối'}")
        
    client.set_callback_new_audio(on_new_audio)
    client.set_callback_connection_change(on_connection_change)
    
    client.start()
    
    try:
        if duration > 0:
            print(f"Đang chạy trong {duration} giây, nhấn Ctrl+C để dừng...")
            time.sleep(duration)
        else:
            print("Đang chạy vô thời hạn, nhấn Ctrl+C để dừng...")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nĐang dừng client...")
    finally:
        client.stop()
        print("Client đã dừng.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Client âm thanh cho Baby Monitor')
    parser.add_argument('--cli', action='store_true', 
                      help='Chạy trong chế độ command line (mặc định: chạy giao diện đồ họa)')
    parser.add_argument('--server', type=str, default=None,
                      help=f'Địa chỉ server (mặc định: {SERVER_HOST})')
    parser.add_argument('--duration', type=int, default=60,
                      help='Thời gian chạy tính theo giây (chỉ áp dụng cho chế độ CLI, 0 = vô hạn)')
    
    args = parser.parse_args()
    
    if args.cli:
        run_cli(server_host=args.server, duration=args.duration)
    else:
        run_gui()