# Clients module for handling different types of client connections

from .audio_client import AudioRecorder
from .camera_client import CameraClient
from .base_client import BaseClient

__all__ = ['AudioRecorder', 'CameraClient', 'BaseClient']
