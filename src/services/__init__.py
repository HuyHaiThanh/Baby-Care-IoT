# Services module for external service integrations

# Services module exports
from .firebase_device_manager import (
    initialize_device,
    register_device,
    update_streaming_status,
    get_device_uuid,
    authenticate_firebase,
    get_ngrok_url,
    is_ngrok_running,
    start_ngrok
)

__all__ = [
    'initialize_device',
    'register_device', 
    'update_streaming_status',
    'get_device_uuid',
    'authenticate_firebase',
    'get_ngrok_url',
    'is_ngrok_running',
    'start_ngrok'
]
