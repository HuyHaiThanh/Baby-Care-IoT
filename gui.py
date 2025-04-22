# File: gui.py
# Giao diện người dùng cho client photo

import tkinter as tk
from tkinter import ttk, messagebox
import os
import threading
import time
from datetime import datetime
from PIL import Image, ImageTk
import asyncio
from config import WINDOW_TITLE, WINDOW_SIZE, DOWNLOAD_DIR, REFRESH_INTERVAL, AUTO_REFRESH

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
        self.current_image_label = None
        self.current_image_object = None
        
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
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tạo frame hiển thị ảnh
        image_frame = ttk.Frame(main_frame)
        image_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Tạo label hiển thị ảnh
        self.image_label = ttk.Label(image_frame, anchor=tk.CENTER)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # Tạo frame điều khiển phía dưới
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=5)
        
        # Tạo các nút điều khiển
        ttk.Button(control_frame, text="<<", command=self.show_previous_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text=">>", command=self.show_next_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Làm mới", command=self.refresh).pack(side=tk.LEFT, padx=5)
        
        # Switch cho auto refresh
        self.auto_refresh_var = tk.BooleanVar(value=self.auto_refresh_enabled)
        ttk.Checkbutton(
            control_frame, 
            text="Tự động làm mới", 
            variable=self.auto_refresh_var, 
            command=self.toggle_auto_refresh
        ).pack(side=tk.LEFT, padx=20)
        
        # Tạo label trạng thái
        self.status_var = tk.StringVar(value="Sẵn sàng")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, anchor=tk.W)
        status_label.pack(fill=tk.X, pady=5)
        
        # Tạo label thông tin ảnh
        self.info_var = tk.StringVar(value="")
        info_label = ttk.Label(main_frame, textvariable=self.info_var, anchor=tk.W)
        info_label.pack(fill=tk.X)
        
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
            else:
                self.info_var.set("Không có ảnh nào")
                self.image_label.configure(image=None)
                self.current_image_object = None
        except Exception as e:
            self.status_var.set(f"Lỗi khi tải danh sách ảnh: {e}")
    
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
            self.status_var.set(f"Lỗi khi hiển thị ảnh: {e}")
    
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
            self.status_var.set(f"Lỗi khi hiển thị ảnh: {e}")
    
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
            width = WINDOW_SIZE[0] - 40
        if height <= 1:
            height = WINDOW_SIZE[1] - 100
        
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
        else:
            self.status_var.set("Đã làm mới")
    
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
            self.status_var.set(f"Đã bật tự động làm mới (mỗi {REFRESH_INTERVAL} giây)")
        else:
            self.stop_auto_refresh()
            self.status_var.set("Đã tắt tự động làm mới")
    
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
        self.status_var.set(f"Đã nhận ảnh mới: {os.path.basename(image_path)}")
    
    def on_close(self):
        """Xử lý khi đóng cửa sổ"""
        self.is_running = False
        self.root.destroy()

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