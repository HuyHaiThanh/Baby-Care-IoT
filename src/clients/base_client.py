# File: src/clients/base_client.py
# Base class for all client types

import threading
import time
from abc import ABC, abstractmethod
from ..utils import logger
from ..network import WebSocketClient

class BaseClient(ABC):
    """
    Base class for all client implementations
    """
    
    def __init__(self, client_type: str, device_id: str):
        """
        Initialize base client
        
        Args:
            client_type (str): Type of client (audio/camera)
            device_id (str): Device identifier
        """
        self.client_type = client_type
        self.device_id = device_id
        self.running = False
        self.ws_client = None
        self.ws_url = None
        self.processing_thread = None
        
    @abstractmethod
    def start(self):
        """Start the client"""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the client"""
        pass
    
    def _create_websocket_client(self, ws_url: str):
        """
        Create WebSocket client
        
        Args:
            ws_url (str): WebSocket URL
        """
        self.ws_url = ws_url
        self.ws_client = WebSocketClient(
            ws_url=ws_url,
            device_id=self.device_id,
            client_type=self.client_type
        )
        
    def _start_websocket(self):
        """Start WebSocket connection"""
        if self.ws_client:
            self.ws_client.connect()
            logger.info(f"{self.client_type} WebSocket connection started")
        else:
            logger.error(f"No WebSocket client available for {self.client_type}")
    
    def _stop_websocket(self):
        """Stop WebSocket connection"""
        if self.ws_client:
            self.ws_client.close()
            logger.info(f"{self.client_type} WebSocket connection stopped")
    
    @property
    def ws_connected(self):
        """Check if WebSocket is connected"""
        return self.ws_client.ws_connected if self.ws_client else False
