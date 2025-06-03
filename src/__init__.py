# Baby Care IoT Package

# Main package exports for src module
from .clients import AudioRecorder, CameraClient, BaseClient
from .core import *
from .network import WebSocketClient
from .services import (
    initialize_device,
    register_device,
    update_streaming_status,
    get_device_uuid,
    authenticate_firebase
)
from .streaming import *
from .utils import logger, set_debug_mode, get_device_info

__all__ = [
    # Clients
    'AudioRecorder',
    'CameraClient', 
    'BaseClient',
    
    # Network
    'WebSocketClient',
    
    # Services
    'initialize_device',
    'register_device',
    'update_streaming_status',
    'get_device_uuid', 
    'authenticate_firebase',
    
    # Utils
    'logger',
    'set_debug_mode',
    'get_device_info'
]
