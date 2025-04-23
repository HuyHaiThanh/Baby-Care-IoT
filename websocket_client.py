import json
import websocket
import threading
import time
import logging
from utils import logger

class WebSocketClient:
    """
    Generic WebSocket client for handling connections to servers
    """
    def __init__(self, ws_url, device_id, client_type="generic"):
        """
        Initialize WebSocket client
        
        Args:
            ws_url (str): WebSocket server URL
            device_id (str): Device identifier
            client_type (str): Type of client (audio/camera)
        """
        self.ws_url = ws_url
        self.device_id = device_id
        self.client_type = client_type
        self.ws = None
        self.ws_connected = False
        self.ws_thread = None
        self.last_ws_status = "Not connected"
        self.running = False
        self.reconnect_interval = 5  # Seconds between reconnection attempts
        self.message_callback = None
    
    def set_message_callback(self, callback):
        """
        Set callback function for message handling
        
        Args:
            callback: Function that takes message data as parameter
        """
        self.message_callback = callback
    
    def _on_ws_message(self, ws, message):
        """
        Handle incoming WebSocket messages
        
        Args:
            ws: WebSocket connection instance
            message: Message received from the server
        """
        try:
            data = json.loads(message)
            logger.info(f"{self.client_type} message received: {data}")
            
            # Execute callback if registered
            if self.message_callback:
                self.message_callback(data)
                
            # Update status
            if "type" in data:
                self.last_ws_status = f"{data['type']} received"
            
        except Exception as e:
            logger.error(f"Error processing {self.client_type} WebSocket message: {e}")

    def _on_ws_error(self, ws, error):
        """
        Handle WebSocket errors
        
        Args:
            ws: WebSocket connection instance
            error: Error information
        """
        logger.error(f"{self.client_type} WebSocket error: {error}")
        self.ws_connected = False
        self.last_ws_status = f"Error: {error}"

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """
        Handle WebSocket connection close
        
        Args:
            ws: WebSocket connection instance
            close_status_code: Status code for the connection closure
            close_msg: Message describing why the connection was closed
        """
        logger.info(f"{self.client_type} WebSocket connection closed: {close_msg}")
        self.ws_connected = False
        self.last_ws_status = "Disconnected"

        # Try to reconnect if client is still running
        if self.running:
            logger.info(f"Attempting to reconnect {self.client_type} WebSocket in {self.reconnect_interval} seconds...")
            time.sleep(self.reconnect_interval)
            self._connect_websocket()

    def _on_ws_open(self, ws):
        """
        Handle WebSocket connection open
        
        Args:
            ws: WebSocket connection instance
        """
        logger.info(f"{self.client_type} WebSocket connection established")
        self.ws_connected = True
        self.last_ws_status = "Connected"
        
        # Send device ID as the first message
        self.ws.send(self.device_id)
        logger.info(f"Sent device ID {self.device_id} to {self.client_type} server")

    def connect(self):
        """
        Start WebSocket connection thread
        """
        self.running = True
        self.ws_thread = threading.Thread(target=self._websocket_thread)
        self.ws_thread.daemon = True
        self.ws_thread.start()
        logger.info(f"{self.client_type} WebSocket thread started")
        
    def _connect_websocket(self):
        """
        Establish connection to WebSocket server
        """
        try:
            if hasattr(self, 'ws') and self.ws:
                self.ws.close()
                
            logger.info(f"Connecting to {self.client_type} WebSocket at {self.ws_url}")
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close
            )
            self.ws.run_forever()
        except Exception as e:
            logger.error(f"Error connecting to {self.client_type} WebSocket: {e}")
            self.ws_connected = False
            time.sleep(self.reconnect_interval)
    
    def _websocket_thread(self):
        """
        Thread for handling WebSocket connection
        """
        # Connection loop
        while self.running:
            if not self.ws_connected:
                self._connect_websocket()
            time.sleep(1)
    
    def send_message(self, data):
        """
        Send message through WebSocket
        
        Args:
            data: Data to send (will be converted to JSON)
            
        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self.ws_connected:
            logger.warning(f"Cannot send {self.client_type} message: WebSocket not connected")
            return False
            
        try:
            self.ws.send(json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Error sending {self.client_type} message: {e}")
            self.ws_connected = False
            self.last_ws_status = f"Send error: {e}"
            return False
    
    def close(self):
        """
        Close WebSocket connection
        """
        self.running = False
        
        if self.ws and self.ws_connected:
            self.ws.close()
            self.ws_connected = False
            
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=1.0)
            
        logger.info(f"{self.client_type} WebSocket connection closed")