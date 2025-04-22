# File: gui.py
# Giao diện người dùng cho client photo

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import threading
import time
from datetime import datetime
from PIL import Image, ImageTk
import asyncio
from config import *

class PhotoClientGUI:
    def __init__(self, root, client):
        """
        Khởi tạo giao diện cho client photo
        
        Args:
            root: Cửa sổ chính Tkinter
            client: Đối tượng PhotoClient
        """
        self.root = root
        self.client = client
        self.image_list = []  # Danh sách đường dẫn ảnh
        self.current_image_index = 0
        self.auto_refresh_enabled = AUTO_REFRESH
        self.auto_refresh_thread = None
        self.is_running = True
        self.current_image_object = None
        self.connected = False
        
        # Thiết lập cửa sổ
        self.setup_window()
        
        # Thiết lập giao diện
        self.setup_ui()
        
        # Load danh sách ảnh
        self.load_image_list()
        
        # Thiết lập callback khi nhận được ảnh mới
        self.client.on_image_received = self.on_new_image
        
        # Khởi động auto refresh nếu được bật
        if self.auto_refresh_enabled:
            self.start_auto_refresh()
    
    def setup_window(self):
        """Thiết lập cửa sổ chính"""
        self.root.title(WINDOW_TITLE)
        self.root.geometry(f"{WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}")
        self.root.minsize(640, 480)
        
        # Thiết lập xử lý khi đóng cửa sổ
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def setup_ui(self):
        """Thiết lập các phần tử giao diện"""
        # Tạo frame chính
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Chia cột cho main frame
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(0, weight=0)  # Control panel
        self.main_frame.rowconfigure(1, weight=1)  # Image display & Log
        
        # Thiết lập thanh trạng thái
        self.setup_status_bar()
        
        # Thiết lập panel điều khiển
        self.setup_control_panel()
        
        # Tạo paned window để chứa panel hiển thị ảnh và panel log
        self.paned_window = ttk.PanedWindow(self.main_frame, orient=tk.HORIZONTAL)
        self.paned_window.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        
        # Thiết lập frame hiển thị ảnh
        self.setup_image_panel()
        
        # Thiết lập panel log
        self.setup_log_panel()
        
        # Đặt kích thước ban đầu cho các panel trong paned window
        self.root.after(100, self.set_initial_pane_sizes)
    
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
        
        # Nút làm mới danh sách ảnh
        self.refresh_button = ttk.Button(
            control_frame, 
            text="Làm mới", 
            command=self.refresh
        )
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        
        # Nút điều hướng
        ttk.Button(control_frame, text="<<", command=self.show_previous_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text=">>", command=self.show_next_image).pack(side=tk.LEFT, padx=5)
        
        # Checkbox tự động làm mới
        self.auto_refresh_var = tk.BooleanVar(value=self.auto_refresh_enabled)
        ttk.Checkbutton(
            control_frame, 
            text="Tự động làm mới", 
            variable=self.auto_refresh_var, 
            command=self.toggle_auto_refresh
        ).pack(side=tk.LEFT, padx=5)
        
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
    
    def setup_image_panel(self):
        """Thiết lập panel hiển thị ảnh"""
        image_frame = ttk.LabelFrame(self.paned_window, text="Hình ảnh từ camera", padding=(10, 5))
        self.paned_window.add(image_frame, weight=1)  # Thêm vào paned window với trọng số cao
        
        # Tạo label hiển thị ảnh
        self.image_label = ttk.Label(image_frame, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # Tạo label thông tin ảnh
        self.info_var = tk.StringVar(value="")
        info_label = ttk.Label(image_frame, textvariable=self.info_var, anchor=tk.W)
        info_label.pack(fill=tk.X, pady=(5, 0))
    
    def setup_log_panel(self):
        """Thiết lập panel log"""
        log_frame = ttk.LabelFrame(self.paned_window, text="Nhật ký", padding=(10, 5))
        self.paned_window.add(log_frame, weight=0)  # Thêm vào paned window với trọng số thấp
        
        # Tạo scrolled text cho log với chiều cao nhỏ hơn
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=6)  # Giảm chiều cao mặc định
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Cấu hình để không thể chỉnh sửa
        self.log_text.configure(state=tk.DISABLED)
        
    def toggle_connection(self):
        """Bật/tắt kết nối"""
        if self.connected:
            self.client.disconnect()
            self.conn_button.configure(text="Kết nối")
            self.log("Đã ngắt kết nối với server.")
            self.connected = False
            self.conn_status_var.set("❌ Mất kết nối")
        else:
            self.client.connect()
            self.conn_button.configure(text="Ngắt kết nối")
            self.log("Đang kết nối đến server...")
            self.connected = True
            self.conn_status_var.set("✅ Đã kết nối")
            
    def connect_to_custom_server(self):
        """Kết nối đến server tùy chỉnh"""
        custom_host = self.server_entry.get().strip()
        if not custom_host:
            messagebox.showerror("Lỗi", "Vui lòng nhập địa chỉ server.")
            return
            
        # Thiết lập server mới
        import config
        config.SERVER_HOST = custom_host
        config.WEBSOCKET_URL = f"ws://{custom_host}:8765"
        
        # Khởi động lại client
        self.client.disconnect()
        time.sleep(1)  # Đợi client dừng hoàn toàn
        self.client.connect(websocket_url=config.WEBSOCKET_URL)
        
        self.log(f"Đang kết nối đến server tùy chỉnh: {custom_host}")
        
    def load_image_list(self):
        """Load danh sách các ảnh trong thư mục"""
        try:
            # Đảm bảo thư mục tồn tại
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            
            # Lọc chỉ các file ảnh
            self.image_list = [
                os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))
            ]
            
            # Sắp xếp theo thời gian (mới nhất lên đầu)
            self.image_list.sort(key=os.path.getmtime, reverse=True)
            
            # Hiển thị ảnh mới nhất nếu có
            if self.image_list:
                self.current_image_index = 0
                self.show_current_image()
                self.status_var.set(f"Có {len(self.image_list)} hình ảnh.")
            else:
                self.info_var.set("Không có ảnh nào")
                self.image_label.configure(image=None)
                self.current_image_object = None
                self.status_var.set("Không có hình ảnh")
        except Exception as e:
            self.log(f"Lỗi khi tải danh sách ảnh: {e}")
    
    def show_current_image(self):
        """Hiển thị ảnh theo chỉ số hiện tại"""
        try:
            if not self.image_list:
                return
                
            image_path = self.image_list[self.current_image_index]
            
            # Load và hiển thị ảnh
            self.display_image(image_path)
            
            # Cập nhật thông tin
            self.update_image_info(image_path)
        except Exception as e:
            self.log(f"Lỗi khi hiển thị ảnh: {e}")
    
    def display_image(self, image_path):
        """
        Load và hiển thị ảnh từ đường dẫn
        
        Args:
            image_path: Đường dẫn đến file ảnh
        """
        try:
            # Load ảnh với PIL
            img = Image.open(image_path)
            
            # Thay đổi kích thước để vừa với label
            img = self.resize_image(img)
            
            # Chuyển sang định dạng Tkinter
            photo = ImageTk.PhotoImage(img)
            
            # Hiển thị ảnh
            self.image_label.configure(image=photo)
            
            # Giữ tham chiếu để tránh garbage collection
            self.current_image_object = photo
        except Exception as e:
            self.log(f"Lỗi khi hiển thị ảnh: {e}")
    
    def resize_image(self, img):
        """
        Thay đổi kích thước ảnh để vừa với label
        
        Args:
            img: Đối tượng PIL.Image
            
        Returns:
            PIL.Image: Ảnh đã thay đổi kích thước
        """
        # Lấy kích thước hiện tại của label
        width = self.image_label.winfo_width()
        height = self.image_label.winfo_height()
        
        # Nếu label chưa được render, dùng kích thước mặc định
        if width <= 1:
            width = WINDOW_SIZE[0] // 2 - 40
        if height <= 1:
            height = WINDOW_SIZE[1] - 150
        
        # Lấy kích thước ảnh
        img_width, img_height = img.size
        
        # Tính toán tỷ lệ để giữ nguyên aspect ratio
        ratio = min(width / img_width, height / img_height)
        new_width = int(img_width * ratio)
        new_height = int(img_height * ratio)
        
        # Thay đổi kích thước
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    def update_image_info(self, image_path):
        """
        Cập nhật thông tin về ảnh hiện tại
        
        Args:
            image_path: Đường dẫn đến file ảnh
        """
        try:
            # Lấy tên file
            file_name = os.path.basename(image_path)
            
            # Lấy thời gian tạo file
            timestamp = os.path.getmtime(image_path)
            time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            
            # Lấy kích thước file
            size_bytes = os.path.getsize(image_path)
            size_str = self.format_size(size_bytes)
            
            # Cập nhật thông tin
            info_text = f"Ảnh: {file_name} | Thời gian: {time_str} | Kích thước: {size_str}"
            self.info_var.set(info_text)
            
            # Cập nhật trạng thái
            status_text = f"Ảnh {self.current_image_index + 1} / {len(self.image_list)}"
            self.status_var.set(status_text)
        except Exception as e:
            self.info_var.set(f"Lỗi khi lấy thông tin ảnh: {e}")
    
    def format_size(self, size_bytes):
        """
        Định dạng kích thước file thành KB hoặc MB
        
        Args:
            size_bytes: Kích thước theo bytes
            
        Returns:
            str: Kích thước đã định dạng
        """
        kb = size_bytes / 1024
        if kb < 1024:
            return f"{kb:.2f} KB"
        else:
            mb = kb / 1024
            return f"{mb:.2f} MB"
    
    def show_next_image(self):
        """Hiển thị ảnh kế tiếp"""
        if not self.image_list:
            return
            
        self.current_image_index = (self.current_image_index + 1) % len(self.image_list)
        self.show_current_image()
    
    def show_previous_image(self):
        """Hiển thị ảnh trước đó"""
        if not self.image_list:
            return
            
        self.current_image_index = (self.current_image_index - 1) % len(self.image_list)
        self.show_current_image()
    
    def refresh(self):
        """Làm mới danh sách ảnh và hiển thị ảnh mới nhất"""
        self.status_var.set("Đang làm mới...")
        self.log("Đang yêu cầu ảnh mới từ server...")
        
        # Yêu cầu ảnh mới từ server
        self.request_latest_image()
        
        # Làm mới danh sách ảnh và hiển thị
        self.root.after(1000, self.reload_images)
    
    def reload_images(self):
        """Tải lại danh sách ảnh và hiển thị"""
        old_count = len(self.image_list)
        self.load_image_list()
        new_count = len(self.image_list)
        
        if new_count > old_count:
            self.status_var.set(f"Đã tải {new_count - old_count} ảnh mới")
            self.log(f"Đã tải {new_count - old_count} ảnh mới")
        else:
            self.status_var.set(f"Có {len(self.image_list)} hình ảnh")
            self.log("Đã làm mới danh sách ảnh")
    
    def request_latest_image(self):
        """Yêu cầu ảnh mới nhất từ server"""
        # Tạo hàm gọi async trong thread chính
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.client.request_latest_image())
            loop.close()
        
        # Chạy trong thread riêng để không block UI
        threading.Thread(target=run_async, daemon=True).start()
    
    def toggle_auto_refresh(self):
        """Bật/tắt chế độ tự động làm mới"""
        self.auto_refresh_enabled = self.auto_refresh_var.get()
        
        if self.auto_refresh_enabled:
            self.start_auto_refresh()
            self.log(f"Đã bật tự động làm mới (mỗi {REFRESH_INTERVAL} giây)")
        else:
            self.stop_auto_refresh()
            self.log("Đã tắt tự động làm mới")
    
    def start_auto_refresh(self):
        """Bắt đầu chế độ tự động làm mới"""
        if self.auto_refresh_thread is None or not self.auto_refresh_thread.is_alive():
            self.auto_refresh_thread = threading.Thread(target=self.auto_refresh_loop, daemon=True)
            self.auto_refresh_thread.start()
    
    def stop_auto_refresh(self):
        """Dừng chế độ tự động làm mới"""
        self.auto_refresh_enabled = False
    
    def auto_refresh_loop(self):
        """Vòng lặp tự động làm mới"""
        while self.is_running and self.auto_refresh_enabled:
            # Yêu cầu ảnh mới
            self.request_latest_image()
            
            # Chờ đến chu kỳ làm mới tiếp theo
            time.sleep(REFRESH_INTERVAL)
            
            # Làm mới UI từ thread chính
            if self.is_running:
                self.root.after(0, self.reload_images)
    
    def on_new_image(self, image_path, image):
        """
        Callback khi nhận được ảnh mới
        
        Args:
            image_path: Đường dẫn đến file ảnh
            image: Đối tượng PIL.Image
        """
        # Cập nhật từ thread chính để tránh lỗi
        self.root.after(0, lambda: self.handle_new_image(image_path))
    
    def handle_new_image(self, image_path):
        """
        Xử lý khi có ảnh mới (chạy trong thread chính)
        
        Args:
            image_path: Đường dẫn đến file ảnh mới
        """
        # Làm mới danh sách ảnh
        self.load_image_list()
        
        # Hiển thị thông báo
        self.log(f"Đã nhận ảnh mới: {os.path.basename(image_path)}")
        messagebox.showinfo("Thông báo", f"Đã nhận ảnh mới từ camera: {os.path.basename(image_path)}")
    
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
        self.is_running = False
        
        try:
            # Dừng client
            if self.client:
                self.client.disconnect()
        except Exception as e:
            print(f"Lỗi khi đóng ứng dụng: {e}")
            
        self.root.destroy()

    def set_initial_pane_sizes(self):
        """Đặt kích thước ban đầu cho các panel trong paned window sau khi giao diện đã được vẽ"""
        width = self.paned_window.winfo_width()
        if width > 10:  # Kiểm tra xem kích thước có hợp lệ không
            # Đặt vị trí phân chia - phần ảnh chiếm 85% không gian, nhật ký 15%
            self.paned_window.sashpos(0, int(width * 0.7))
        else:
            # Nếu chưa có kích thước hợp lệ, thử lại sau 100ms
            self.root.after(100, self.set_initial_pane_sizes)


def create_gui(client):
    """
    Tạo và khởi động giao diện
    
    Args:
        client: Đối tượng PhotoClient
        
    Returns:
        Tk: Đối tượng root Tkinter
    """
    root = tk.Tk()
    app = PhotoClientGUI(root, client)
    return root