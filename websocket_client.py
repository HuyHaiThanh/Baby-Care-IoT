import json
import websocket
import threading
import time
import logging
import traceback
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
        
        # Add parameters for exponential backoff
        self.max_reconnect_interval = 60  # Maximum seconds between reconnection attempts
        self.current_reconnect_interval = self.reconnect_interval  # Current interval, will increase with failures
        self.reconnect_attempt = 0
        self.max_reconnect_attempts = 10  # Maximum number of consecutive reconnection attempts
        
        logger.info(f"Initialized {client_type} WebSocket client with URL: {ws_url}")
    
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
            logger.error(traceback.format_exc())

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

        # Connection will be handled by the main _websocket_thread loop
        # No need to directly attempt reconnection here as it creates duplicate attempts
        logger.info(f"{self.client_type} WebSocket connection closed. Reconnection will be handled by main thread.")

    def _on_ws_open(self, ws):
        """
        Handle WebSocket connection open
        
        Args:
            ws: WebSocket connection instance
        """
        logger.info(f"{self.client_type} WebSocket connection established")
        self.ws_connected = True
        self.last_ws_status = "Connected"
        
        # Don't send any initial message - the server doesn't expect one
        # The client_id is already in the URL path and the server will extract it from there

    def connect(self):
        """
        Start WebSocket connection thread
        """
        try:
            self.running = True
            self.ws_thread = threading.Thread(target=self._websocket_thread)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            logger.info(f"{self.client_type} WebSocket thread started")
        except Exception as e:
            logger.error(f"Error starting {self.client_type} WebSocket thread: {e}")
            logger.error(traceback.format_exc())
            self.running = False
            return False
        return True
        
    def _connect_websocket(self):
        """
        Establish connection to WebSocket server
        """
        try:
            if hasattr(self, 'ws') and self.ws:
                self.ws.close()
                
            logger.info(f"Connecting to {self.client_type} WebSocket at {self.ws_url}")
            
            # Reduce verbosity of websocket logging in production
            websocket.enableTrace(False)
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close
            )
            
            # Use non-blocking call to run_forever() so we can handle exceptions
            ws_thread = threading.Thread(target=self._run_websocket)
            ws_thread.daemon = True
            ws_thread.start()
            
            # Give a short time for the connection to establish
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error connecting to {self.client_type} WebSocket: {e}")
            logger.error(traceback.format_exc())
            self.ws_connected = False
            # Don't sleep here, let _websocket_thread handle the timing
            # and attempt counting for reconnection attempts
    
    def _run_websocket(self):
        """
        Run the WebSocket connection with exception handling
        """
        try:
            self.ws.run_forever()
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            logger.error(traceback.format_exc())
            self.ws_connected = False
    
    def _websocket_thread(self):
        """
        Thread for handling WebSocket connection
        """
        # Connection loop
        while self.running:
            try:
                if not self.ws_connected:
                    # Check if we've reached the maximum number of reconnection attempts
                    if self.reconnect_attempt >= self.max_reconnect_attempts:
                        logger.warning(f"Reached maximum reconnection attempts ({self.max_reconnect_attempts}) for {self.client_type} WebSocket. Stopping reconnection attempts.")
                        # Reset attempt counter but wait for long interval before trying again
                        self.reconnect_attempt = 0
                        time.sleep(self.max_reconnect_interval * 2)
                    else:
                        # Try to connect
                        self._connect_websocket()
                        
                        # If we're still not connected after the attempt, increase the attempt counter
                        # and wait for the current reconnect interval before the next attempt
                        if not self.ws_connected:
                            self.reconnect_attempt += 1
                            logger.info(f"Connection attempt {self.reconnect_attempt}/{self.max_reconnect_attempts} failed. " +
                                      f"Next attempt in {self.current_reconnect_interval} seconds.")
                            time.sleep(self.current_reconnect_interval)
                            # Increase the reconnect interval for the next attempt (exponential backoff)
                            self.current_reconnect_interval = min(self.current_reconnect_interval * 2, self.max_reconnect_interval)
                else:
                    # If we're connected, reset the reconnection parameters
                    if self.reconnect_attempt > 0:
                        logger.info(f"Connection restored for {self.client_type} WebSocket. Resetting reconnection parameters.")
                        self.reconnect_attempt = 0
                        self.current_reconnect_interval = self.reconnect_interval
                    
                    # Connected and healthy, sleep for a short time before checking again
                    time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in WebSocket thread: {e}")
                logger.error(traceback.format_exc())
                time.sleep(self.current_reconnect_interval)
                self.reconnect_attempt += 1
                self.current_reconnect_interval = min(self.current_reconnect_interval * 2, self.max_reconnect_interval)
    
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
            logger.error(traceback.format_exc())
            self.ws_connected = False
            self.last_ws_status = f"Send error: {e}"
            return False
    
    def close(self):
        """
        Close WebSocket connection
        """
        self.running = False
        
        try:
            if self.ws and self.ws_connected:
                self.ws.close()
                self.ws_connected = False
                
            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=1.0)
                
            logger.info(f"{self.client_type} WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error closing {self.client_type} WebSocket connection: {e}")
            logger.error(traceback.format_exc())