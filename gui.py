# File: gui.py
# Giao diện đồ họa cho client âm thanh

import os
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
from datetime import datetime
import PIL.Image
import PIL.ImageTk
from config import *
from audio_client import AudioClient

class AudioClientGUI:
    """
    Giao diện đồ họa cho client âm thanh
    """
    def __init__(self, root):
        self.root = root
        self.root.title(GUI_TITLE)
        self.root.geometry(f"{GUI_WIDTH}x{GUI_HEIGHT}")
        self.root.minsize(600, 400)
        
        # Biến theo dõi trạng thái
        self.client = AudioClient()
        self.connected = False
        self.received_audios = []
        self.is_playing = False
        
        # Tạo thư mục lưu âm thanh nếu chưa tồn tại
        os.makedirs(AUDIO_DIR, exist_ok=True)
        
        # Thiết lập frame chính
        self.setup_main_frame()
        
        # Thiết lập các phần tử giao diện
        self.setup_status_bar()
        self.setup_control_panel()
        self.setup_audio_list()
        self.setup_log_panel()
        
        # Đăng ký callbacks
        self.client.set_callback_new_audio(self.on_new_audio)
        self.client.set_callback_connection_change(self.on_connection_change)
        
        # Khởi động client trong một thread riêng
        self.start_client()
        
        # Thiết lập hàm xử lý khi đóng cửa sổ
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def setup_main_frame(self):
        """Thiết lập frame chính"""
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Chia cột cho main frame
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(0, weight=0)  # Control panel
        self.main_frame.rowconfigure(1, weight=1)  # Audio list & Log
        
    def setup_status_bar(self):
        """Thiết lập thanh trạng thái"""
        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.conn_status_var = tk.StringVar(value="Đang kết nối...")
        self.conn_status_label = ttk.Label(
            self.status_bar, 
            textvariable=self.conn_status_var,
            padding=(5, 2)
        )
        self.conn_status_label.pack(side=tk.LEFT)
        
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self.status_label = ttk.Label(
            self.status_bar, 
            textvariable=self.status_var,
            padding=(5, 2)
        )
        self.status_label.pack(side=tk.RIGHT)
        
    def setup_control_panel(self):
        """Thiết lập panel điều khiển"""
        control_frame = ttk.LabelFrame(self.main_frame, text="Điều khiển", padding=(10, 5))
        control_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Nút kết nối/ngắt kết nối
        self.conn_button = ttk.Button(
            control_frame, 
            text="Kết nối", 
            command=self.toggle_connection
        )
        self.conn_button.pack(side=tk.LEFT, padx=5)
        
        # Nút làm mới danh sách âm thanh
        self.refresh_button = ttk.Button(
            control_frame, 
            text="Làm mới", 
            command=self.refresh_audio_list,
            state=tk.DISABLED
        )
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        
        # Nút dừng phát âm thanh
        self.stop_button = ttk.Button(
            control_frame, 
            text="Dừng phát", 
            command=self.stop_playback,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # Địa chỉ server
        ttk.Label(control_frame, text="Địa chỉ server:").pack(side=tk.LEFT, padx=(20, 5))
        self.server_entry = ttk.Entry(control_frame, width=20)
        self.server_entry.pack(side=tk.LEFT, padx=5)
        self.server_entry.insert(0, SERVER_HOST)
        
        # Nút kết nối đến server tùy chỉnh
        self.connect_custom_button = ttk.Button(
            control_frame, 
            text="Kết nối tới", 
            command=self.connect_to_custom_server
        )
        self.connect_custom_button.pack(side=tk.LEFT, padx=5)
        
    def setup_audio_list(self):
        """Thiết lập danh sách âm thanh"""
        audio_frame = ttk.LabelFrame(
            self.main_frame, 
            text="Danh sách âm thanh (Nhấp đúp để phát)",
            padding=(10, 5)
        )
        audio_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        
        # Tạo Treeview cho danh sách âm thanh
        self.audio_tree = ttk.Treeview(
            audio_frame,
            columns=("timestamp", "type", "path"),
            show="headings",
            selectmode="browse"
        )
        
        # Thiết lập các cột
        self.audio_tree.heading("timestamp", text="Thời gian")
        self.audio_tree.heading("type", text="Loại")
        self.audio_tree.heading("path", text="Tệp")
        
        self.audio_tree.column("timestamp", width=150)
        self.audio_tree.column("type", width=100)
        self.audio_tree.column("path", width=250)
        
        # Thêm scrollbar
        scrollbar = ttk.Scrollbar(audio_frame, orient="vertical", command=self.audio_tree.yview)
        self.audio_tree.configure(yscrollcommand=scrollbar.set)
        
        # Đóng gói
        self.audio_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Đăng ký sự kiện double-click
        self.audio_tree.bind("<Double-1>", self.on_audio_double_click)
        
    def setup_log_panel(self):
        """Thiết lập panel log"""
        log_frame = ttk.LabelFrame(self.main_frame, text="Nhật ký", padding=(10, 5))
        log_frame.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        
        # Tạo scrolled text cho log
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Cấu hình để không thể chỉnh sửa
        self.log_text.configure(state=tk.DISABLED)
        
    def start_client(self):
        """Khởi động audio client"""
        self.log("Đang khởi động client...")
        self.client.start()
        
    def toggle_connection(self):
        """Bật/tắt kết nối"""
        if self.connected:
            self.client.stop()
            self.conn_button.configure(text="Kết nối")
            self.log("Đã ngắt kết nối với server.")
        else:
            self.client.start()
            self.conn_button.configure(text="Ngắt kết nối")
            self.log("Đang kết nối đến server...")
            
    def connect_to_custom_server(self):
        """Kết nối đến server tùy chỉnh"""
        custom_host = self.server_entry.get().strip()
        if not custom_host:
            messagebox.showerror("Lỗi", "Vui lòng nhập địa chỉ server.")
            return
            
        # Thiết lập server mới
        import config
        config.SERVER_HOST = custom_host
        
        # Khởi động lại client
        self.client.stop()
        time.sleep(1)  # Đợi client dừng hoàn toàn
        self.client = AudioClient()
        self.client.set_callback_new_audio(self.on_new_audio)
        self.client.set_callback_connection_change(self.on_connection_change)
        self.client.start()
        
        self.log(f"Đang kết nối đến server tùy chỉnh: {custom_host}")
        
    def refresh_audio_list(self):
        """Làm mới danh sách âm thanh từ thư mục"""
        # Xóa danh sách hiện tại
        for item in self.audio_tree.get_children():
            self.audio_tree.delete(item)
            
        self.received_audios = []
        
        # Kiểm tra thư mục âm thanh
        if not os.path.exists(AUDIO_DIR):
            self.log("Không tìm thấy thư mục âm thanh.")
            return
            
        # Thêm files vào danh sách
        try:
            for file in os.listdir(AUDIO_DIR):
                if file.endswith(".wav"):
                    filepath = os.path.join(AUDIO_DIR, file)
                    
                    # Trích xuất thời gian từ tên file
                    try:
                        # Tên file dự kiến: audio_YYYYMMDD_HHMMSS.wav hoặc crying_YYYYMMDD_HHMMSS.wav
                        if file.startswith("audio_"):
                            timestamp_str = file[6:-4]  # Cắt "audio_" và ".wav"
                            audio_type = "Âm thanh"
                        elif file.startswith("crying_"):
                            timestamp_str = file[7:-4]  # Cắt "crying_" và ".wav"
                            audio_type = "Tiếng khóc"
                        else:
                            timestamp_str = file[:-4]  # Chỉ cắt ".wav"
                            audio_type = "Khác"
                            
                        # Thêm vào treeview
                        item_id = self.audio_tree.insert("", "end", values=(
                            timestamp_str.replace("_", " ").replace("-", ":"),
                            audio_type,
                            file
                        ))
                        
                        # Lưu vào danh sách để truy cập nhanh
                        self.received_audios.append({
                            "path": filepath,
                            "tree_id": item_id,
                            "timestamp": timestamp_str,
                            "type": audio_type
                        })
                    except Exception as e:
                        self.log(f"Lỗi khi xử lý file {file}: {e}")
                        
            # Sắp xếp theo thời gian
            self.audio_tree.configure(height=min(10, len(self.received_audios)))
            
            self.log(f"Đã tìm thấy {len(self.received_audios)} file âm thanh.")
            self.status_var.set(f"Có {len(self.received_audios)} âm thanh.")
            
        except Exception as e:
            self.log(f"Lỗi khi làm mới danh sách âm thanh: {e}")
            
    def on_audio_double_click(self, event):
        """Xử lý khi người dùng nhấp đúp vào một mục âm thanh"""
        # Lấy mục đã chọn
        selection = self.audio_tree.selection()
        if not selection:
            return
            
        item = selection[0]
        values = self.audio_tree.item(item, "values")
        if not values or len(values) < 3:
            return
            
        # Lấy đường dẫn đầy đủ
        filename = values[2]
        filepath = os.path.join(AUDIO_DIR, filename)
        
        # Phát âm thanh
        if os.path.exists(filepath):
            self.log(f"Đang phát âm thanh: {filename}")
            self.client.play_audio(audio_file=filepath)
            self.is_playing = True
            self.stop_button.configure(state=tk.NORMAL)
        else:
            self.log(f"Không tìm thấy file: {filepath}")
            
    def stop_playback(self):
        """Dừng phát âm thanh hiện tại"""
        self.client.stop_audio()
        self.is_playing = False
        self.stop_button.configure(state=tk.DISABLED)
        self.log("Đã dừng phát âm thanh.")
        
    def on_new_audio(self, audio_path, is_crying):
        """Callback khi có âm thanh mới từ server"""
        self.log(f"Nhận được {'tiếng khóc' if is_crying else 'âm thanh'} mới: {os.path.basename(audio_path)}")
        
        # Tự động làm mới danh sách
        self.refresh_audio_list()
        
        # Thông báo nếu là tiếng khóc
        if is_crying:
            self.show_crying_notification()
            
    def on_connection_change(self, connected):
        """Callback khi trạng thái kết nối thay đổi"""
        self.connected = connected
        
        if connected:
            self.conn_status_var.set("✅ Đã kết nối")
            self.conn_button.configure(text="Ngắt kết nối")
            self.refresh_button.configure(state=tk.NORMAL)
            self.log("Đã kết nối đến server.")
            
            # Làm mới danh sách khi kết nối
            self.refresh_audio_list()
        else:
            self.conn_status_var.set("❌ Mất kết nối")
            self.conn_button.configure(text="Kết nối")
            self.log("Mất kết nối đến server.")
            
    def show_crying_notification(self):
        """Hiển thị thông báo khi phát hiện tiếng khóc"""
        # Hiển thị thông báo trên giao diện
        self.status_var.set("⚠️ PHÁT HIỆN TIẾNG KHÓC!")
        
        # Reset trạng thái sau một khoảng thời gian
        def reset_status():
            time.sleep(5)
            self.status_var.set(f"Có {len(self.received_audios)} âm thanh.")
            
        # Chạy trong thread riêng để không chặn giao diện
        threading.Thread(target=reset_status, daemon=True).start()
        
        # Hiển thị message box
        messagebox.showwarning(
            "Cảnh báo",
            "⚠️ PHÁT HIỆN TIẾNG KHÓC CỦA EM BÉ!"
        )
        
    def log(self, message):
        """Thêm thông điệp vào panel log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"
        
        # Cập nhật log trong thread giao diện chính
        self.root.after(0, self._update_log, log_message)
        
    def _update_log(self, message):
        """Cập nhật log (chạy trong thread giao diện)"""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)  # Cuộn xuống cuối
        self.log_text.configure(state=tk.DISABLED)
        
    def on_close(self):
        """Xử lý khi đóng cửa sổ"""
        self.log("Đang đóng ứng dụng...")
        
        try:
            # Dừng client
            if self.client:
                self.client.stop()
        except Exception as e:
            print(f"Lỗi khi đóng ứng dụng: {e}")
            
        self.root.destroy()


# Hàm chạy ứng dụng
def run_app():
    root = tk.Tk()
    app = AudioClientGUI(root)
    root.mainloop()


# Chạy ứng dụng khi chạy trực tiếp
if __name__ == "__main__":
    run_app()