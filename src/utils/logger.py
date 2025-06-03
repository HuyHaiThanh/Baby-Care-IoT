# File: src/utils/logger.py
# Module xử lý logging và debug

import os
import logging
import logging.handlers

# Tạo thư mục logs nếu chưa tồn tại
logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Biến global để kiểm soát hiển thị log
DEBUG_MODE = False

# Cấu hình logging - MẶC ĐỊNH KHÔNG HIỂN THỊ
logger = logging.getLogger('pi-client')
logger.setLevel(logging.INFO)

# Định dạng log
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Handler cho file log
file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=os.path.join(logs_dir, 'babycare.log'),
    when='midnight',
    backupCount=7
)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

# Handler riêng cho lỗi
error_file_handler = logging.handlers.RotatingFileHandler(
    filename=os.path.join(logs_dir, 'error.log'),
    maxBytes=2*1024*1024,
    backupCount=5
)
error_file_handler.setFormatter(log_format)
error_file_handler.setLevel(logging.ERROR)
logger.addHandler(error_file_handler)

# Mặc định không hiển thị log lên console - cần NullHandler
class NullHandler(logging.Handler):
    def emit(self, record):
        pass

# Áp dụng NullHandler để không hiện log lên console
null_handler = NullHandler()
logger.addHandler(null_handler)

def set_debug_mode(enabled=False):
    """
    Bật hoặc tắt chế độ debug
    
    Args:
        enabled (bool): True để hiển thị log lên console, False để không hiển thị
    """
    global DEBUG_MODE
    DEBUG_MODE = enabled
    
    # Xóa tất cả handlers hiện tại
    for hdlr in logger.handlers[:]:
        if isinstance(hdlr, (logging.StreamHandler, NullHandler)):
            logger.removeHandler(hdlr)
    
    if enabled:
        # Bật chế độ debug - thêm handler để hiển thị lên console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        logger.addHandler(console_handler)
        logger.info("Debug mode activated - Logging to console is ON")
    else:
        # Tắt chế độ debug - thêm NullHandler để không hiện log
        logger.addHandler(NullHandler())
