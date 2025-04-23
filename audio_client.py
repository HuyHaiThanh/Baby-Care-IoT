# File: audio_client.py
# Module for recording and sending audio to server

import pyaudio
import numpy as np
import wave
import time
import threading
import queue
import base64
import json
from io import BytesIO
from config import (
    AUDIO_WS_ENDPOINT, SAMPLE_RATE, CHANNELS, 
    AUDIO_DURATION, AUDIO_SLIDE_SIZE, DEVICE_ID
)
from utils import logger
from websocket_client import WebSocketClient

class AudioRecorder:
    """
    Records audio using a sliding window approach.
    
    This class records audio continuously and processes it in overlapping windows.
    With default settings, it creates 3-second audio chunks that slide by 1 second,
    meaning there is a 2-second overlap between consecutive chunks.
    """
    def __init__(self, chunk_size=1024, sample_rate=SAMPLE_RATE, channels=CHANNELS, 
                 window_size=AUDIO_DURATION, slide_size=AUDIO_SLIDE_SIZE, format=pyaudio.paInt16):
        """
        Initialize the AudioRecorder with the specified parameters.
        
        Args:
            chunk_size (int): Number of audio frames per buffer
            sample_rate (int): Audio sampling rate in Hz (default 16000)
            channels (int): Number of audio channels (1=mono, 2=stereo)
            window_size (int): Size of each audio segment in seconds (default 3)
            slide_size (int): How much the window slides each time in seconds (default 1)
            format: PyAudio format constant
        """
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.window_size = window_size
        self.slide_size = slide_size
        
        # WebSocket URL
        ws_url = f"{AUDIO_WS_ENDPOINT}/{DEVICE_ID}"
        logger.info(f"Audio WebSocket URL: {ws_url}")
        
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.frames_per_window = int(sample_rate * window_size)
        self.frames_per_slide = int(sample_rate * slide_size)
        self.chunk_queue = queue.Queue()
        self.save_counter = 0
        self.processing_thread = None
        
        # Create WebSocket client
        self.ws_client = WebSocketClient(
            ws_url=ws_url,
            device_id=DEVICE_ID,
            client_type="audio"
        )
        self.last_ws_status = "Not connected"

    def start_recording(self):
        """
        Start recording audio and establish WebSocket connection.
        
        This method:
        1. Connects to the WebSocket server
        2. Initializes the audio buffer
        3. Sets up the PyAudio stream with callback
        4. Starts the audio processing thread
        """
        if self.is_recording:
            return
            
        # Connect to WebSocket first
        self.ws_client.connect()
        
        self.is_recording = True
        self.audio_buffer = []
        
        def callback(in_data, frame_count, time_info, status):
            self.audio_buffer.append(np.frombuffer(in_data, dtype=np.int16))
            return (in_data, pyaudio.paContinue)
            
        self.stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            stream_callback=callback
        )
        
        self.processing_thread = threading.Thread(target=self._process_audio)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        logger.info("Started audio recording with sliding window")
        
    def _process_audio(self):
        """
        Process audio in sliding windows.
        
        This method continuously monitors the audio buffer. Once enough data 
        is collected for a window (e.g., 3 seconds), it processes that window
        and then slides forward by slide_size (e.g., 1 second) to prepare for
        the next window.
        
        This runs in a separate thread to avoid blocking the main thread.
        """
        frames_accumulated = 0
        samples_per_chunk = self.chunk_size
        buffer_ready = False
        
        while self.is_recording:
            if len(self.audio_buffer) > 0:
                with self.buffer_lock:
                    total_samples_in_buffer = sum(len(chunk) for chunk in self.audio_buffer)
                    frames_accumulated = total_samples_in_buffer
                    
                    if not buffer_ready and frames_accumulated >= self.frames_per_window:
                        buffer_ready = True
                    
                    if buffer_ready and frames_accumulated >= self.frames_per_window:
                        flat_buffer = np.concatenate(self.audio_buffer)
                        window_data = flat_buffer[-self.frames_per_window:]
                        
                        if len(window_data) == self.frames_per_window:
                            self.process_window(window_data)
                        else:
                            logger.warning("Not enough data for a full window. Waiting for more data...")
                            continue
                        
                        samples_to_remove = self.frames_per_slide
                        while samples_to_remove > 0 and len(self.audio_buffer) > 0:
                            if len(self.audio_buffer[0]) <= samples_to_remove:
                                samples_to_remove -= len(self.audio_buffer[0])
                                self.audio_buffer.pop(0)
                            else:
                                self.audio_buffer[0] = self.audio_buffer[0][samples_to_remove:]
                                samples_to_remove = 0
                        
                        frames_accumulated = sum(len(chunk) for chunk in self.audio_buffer)
                        
            time.sleep(0.1)
    
    def process_window(self, window_data):
        """
        Process a single window of audio data.
        
        Takes a window of audio data and sends it through WebSocket if connected.
        Each window is sent in a separate thread to avoid blocking.
        
        Args:
            window_data (numpy.ndarray): Audio data for the current window (3 seconds)
        """
        self.chunk_queue.put(window_data)
        chunk_id = f"audio_chunk_{self.save_counter}"
        
        # Send to WebSocket if connected
        if self.ws_client.ws_connected:
            ws_send_thread = threading.Thread(
                target=self.send_to_websocket,
                args=(window_data, chunk_id)
            )
            ws_send_thread.daemon = True
            ws_send_thread.start()
        
        self.save_counter += 1
    
    def send_to_websocket(self, audio_data, chunk_id):
        """
        Send audio data through WebSocket connection.
        
        Converts audio data to WAV format, encodes it as base64, and sends it through
        the WebSocket connection with appropriate metadata.
        
        Args:
            audio_data (numpy.ndarray): Audio data to send (3 seconds)
            chunk_id (str): Identifier for this audio chunk
        """
        if not self.ws_client.ws_connected:
            return

        try:
            # Convert audio data to WAV format in memory
            buffer = BytesIO()
            wf = wave.open(buffer, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())
            wf.close()
            
            # Get the WAV data from the buffer
            buffer.seek(0)
            wav_data = buffer.read()
            
            # Encode the WAV data as base64
            encoded_data = base64.b64encode(wav_data).decode('utf-8')
            
            # Prepare the payload
            payload = {
                'type': 'audio',
                'chunk_id': chunk_id,
                'timestamp': time.time(),
                'sample_rate': self.sample_rate,
                'channels': self.channels,
                'device_id': DEVICE_ID,
                'audio_data': encoded_data
            }
            
            # Send through WebSocket
            result = self.ws_client.send_message(payload)
            if result:
                self.last_ws_status = "Data sent"
                logger.info(f"Audio sent via WebSocket: {chunk_id}")
            
        except Exception as e:
            logger.error(f"Error sending audio through WebSocket: {e}")
            self.last_ws_status = f"Send error: {str(e)}"
    
    def stop_recording(self):
        """
        Stop recording and clean up resources.
        
        This method:
        1. Stops the recording process
        2. Closes the audio stream
        3. Closes the WebSocket connection
        4. Waits for processing threads to finish
        """
        self.is_recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        # Close WebSocket
        self.ws_client.close()
        
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)
        
        logger.info("Audio recording stopped")
        
    def close(self):
        """
        Close all resources and terminate PyAudio.
        
        This should be called when the application exits to ensure proper cleanup.
        """
        self.stop_recording()
        self.audio.terminate()
        
    @property
    def ws_connected(self):
        """
        Property to check WebSocket connection status
        
        Returns:
            bool: True if WebSocket is connected, False otherwise
        """
        return self.ws_client.ws_connected


# Test module when run directly
if __name__ == "__main__":
    # Initialize AudioRecorder
    audio_recorder = AudioRecorder()
    
    try:
        # Start recording
        audio_recorder.start_recording()
        
        # Record for 60 seconds
        logger.info("Recording and sending audio for 60 seconds...")
        time.sleep(60)
        
    except KeyboardInterrupt:
        logger.info("Stop signal received")
    finally:
        # Stop recording and release resources
        audio_recorder.stop_recording()
        audio_recorder.close()
        logger.info("Test completed")