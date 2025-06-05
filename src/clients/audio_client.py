# File: src/clients/audio_client.py
# Module for recording and sending audio to server

import pyaudio
import numpy as np
import wave
import time
import threading
import queue
import base64
import json
import os
import sys
from io import BytesIO
from scipy import signal
from contextlib import contextmanager

from ..core.config import (
    AUDIO_WS_ENDPOINT, SAMPLE_RATE, CHANNELS, 
    AUDIO_DURATION, AUDIO_SLIDE_SIZE, DEVICE_ID,
    USE_VAD, get_ws_url
)
from ..utils import logger
from ..network import WebSocketClient
from .base_client import BaseClient

class AudioRecorder(BaseClient):
    """
    Records audio using a sliding window approach.
    
    This class records audio continuously and processes it in overlapping windows.
    With default settings, it creates 3-second audio chunks that slide by 1 second,
    meaning there is a 2-second overlap between consecutive chunks.
    """
    
    @staticmethod
    @contextmanager
    def suppress_alsa_errors():
        """Context manager to suppress ALSA error messages"""
        # Save the original stderr
        original_stderr = os.dup(2)
        # Redirect stderr to /dev/null (or NUL on Windows)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        try:
            yield
        finally:
            # Restore original stderr
            os.dup2(original_stderr, 2)
            os.close(devnull)
            os.close(original_stderr)
    
    def find_usb_audio_device(self):
        """
        Find USB audio input device index.
        
        Returns:
            int: Device index of USB audio device, or None if not found
        """
        try:
            with self.suppress_alsa_errors():
                audio = pyaudio.PyAudio()
                device_count = audio.get_device_count()
                
                logger.info(f"Scanning {device_count} audio devices for USB microphone...")
                
                for i in range(device_count):
                    try:
                        device_info = audio.get_device_info_by_index(i)
                        device_name = device_info.get('name', '').lower()
                        max_input_channels = device_info.get('maxInputChannels', 0)
                        
                        logger.info(f"Device {i}: {device_info.get('name', 'Unknown')} - Input channels: {max_input_channels}")
                        
                        # Look for USB audio devices with input capability
                        if (max_input_channels > 0 and 
                            ('usb' in device_name or 'composite' in device_name or 
                             'microphone' in device_name or 'mic' in device_name)):
                            logger.info(f"Found USB audio input device: {device_info['name']} (Index: {i})")
                            audio.terminate()
                            return i
                            
                    except Exception as e:
                        logger.debug(f"Error checking device {i}: {e}")
                        continue
                
                audio.terminate()
                logger.warning("No USB audio input device found, will use default device")
                return None
                
        except Exception as e:
            logger.error(f"Error finding USB audio device: {e}")
            return None
    def __init__(self, chunk_size=1024, sample_rate=SAMPLE_RATE, channels=CHANNELS, 
                 window_size=AUDIO_DURATION, slide_size=AUDIO_SLIDE_SIZE, format=pyaudio.paInt16,
                 max_queue_size=10):
        """
        Initialize the AudioRecorder with the specified parameters.
        
        Args:
            chunk_size (int): Number of audio frames per buffer
            sample_rate (int): Audio sampling rate in Hz (default 16000)
            channels (int): Number of audio channels (1=mono, 2=stereo)
            window_size (int): Size of each audio segment in seconds (default 3)
            slide_size (int): How much the window slides each time in seconds (default 1)
            format: PyAudio format constant
            max_queue_size (int): Maximum number of audio chunks in the queue (default 10)
        """
        super().__init__(client_type="audio", device_id=DEVICE_ID)
        
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.window_size = window_size
        self.slide_size = slide_size
        self.max_queue_size = max_queue_size
        
        # Voice Activity Detection settings
        self.use_vad = USE_VAD
        self.vad_min_freq = 250  # Minimum frequency for VAD in Hz
        self.vad_max_freq = 750  # Maximum frequency for VAD in Hz
        self.total_chunks = 0
        self.vad_active_chunks = 0
        
        # Find USB audio device
        self.usb_device_index = self.find_usb_audio_device()
        
        with self.suppress_alsa_errors():
            self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.frames_per_window = int(sample_rate * window_size)
        self.frames_per_slide = int(sample_rate * slide_size)
        self.chunk_queue = queue.Queue(maxsize=max_queue_size)
        self.save_counter = 0
        self.dropped_chunks_count = 0
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
        
        # Get the most up-to-date WebSocket URL
        base_ws_url = get_ws_url('audio')
        ws_url = f"{base_ws_url}/{DEVICE_ID}"
        logger.info(f"Connecting to audio WebSocket at {ws_url}")
        
        # Create WebSocket client with the updated URL
        self._create_websocket_client(ws_url)
        
        # Connect to WebSocket first
        self._start_websocket()
        
        self.is_recording = True
        self.audio_buffer = []
        
        def callback(in_data, frame_count, time_info, status):
            self.audio_buffer.append(np.frombuffer(in_data, dtype=np.int16))
            return (in_data, pyaudio.paContinue)
        
        try:
            # Prepare stream parameters
            stream_params = {
                'format': self.format,
                'channels': self.channels,
                'rate': self.sample_rate,
                'input': True,
                'frames_per_buffer': self.chunk_size,
                'stream_callback': callback
            }
            
            # Add USB device index if found
            if self.usb_device_index is not None:
                stream_params['input_device_index'] = self.usb_device_index
                logger.info(f"Using USB audio device index: {self.usb_device_index}")
            else:
                logger.info("Using default audio input device")
            
            # Create audio stream with ALSA error suppression
            with self.suppress_alsa_errors():
                self.stream = self.audio.open(**stream_params)
                
        except Exception as e:
            logger.error(f"Failed to initialize audio stream: {e}")
            self.is_recording = False
            return
        
        self.processing_thread = threading.Thread(target=self._process_audio)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        logger.info("Started audio recording with sliding window")

    def start(self):
        """Start the audio client"""
        self.running = True
        self.start_recording()
        return True

    def _process_audio(self):
        """
        Process audio data using sliding window technique.
        
        This method continuously processes buffered audio data in overlapping windows.
        It collects enough frames for a complete window, processes the window,
        then slides the window forward by removing processed frames.
        """
        while self.is_recording:
            try:
                with self.buffer_lock:
                    # Calculate total frames in buffer
                    frames_accumulated = sum(len(chunk) for chunk in self.audio_buffer)
                    
                    # Check if we have enough frames for a complete window
                    if frames_accumulated >= self.frames_per_window:
                        # Collect frames for the current window
                        window_data = np.array([], dtype=np.int16)
                        frames_needed = self.frames_per_window
                        
                        for chunk in self.audio_buffer[:]:
                            if frames_needed <= 0:
                                break
                            frames_to_take = min(len(chunk), frames_needed)
                            window_data = np.concatenate([window_data, chunk[:frames_to_take]])
                            frames_needed -= frames_to_take
                        
                        # Process the window if we have the correct amount of data
                        if len(window_data) == self.frames_per_window:
                            self.process_window(window_data)
                        else:
                            logger.warning("Not enough data for a full window. Waiting for more data...")
                            continue
                        
                        # Slide the window by removing processed frames
                        samples_to_remove = self.frames_per_slide
                        while samples_to_remove > 0 and len(self.audio_buffer) > 0:
                            if len(self.audio_buffer[0]) <= samples_to_remove:
                                samples_to_remove -= len(self.audio_buffer[0])
                                self.audio_buffer.pop(0)
                            else:
                                self.audio_buffer[0] = self.audio_buffer[0][samples_to_remove:]
                                samples_to_remove = 0
                        frames_accumulated = sum(len(chunk) for chunk in self.audio_buffer)
                        
            except Exception as e:
                logger.error(f"Error in audio processing: {e}")
                
            time.sleep(0.1)

    def detect_voice_activity(self, audio_data):
        """
        Simple Voice Activity Detection using frequency domain analysis.
        
        Args:
            audio_data (numpy.ndarray): Audio data to analyze
            
        Returns:
            bool: True if voice activity detected, False otherwise
        """
        if not self.use_vad:
            return True  # If VAD is disabled, always return True
        
        try:
            # Perform FFT to get frequency components
            fft_data = np.abs(np.fft.fft(audio_data))
            freqs = np.fft.fftfreq(len(audio_data), 1/self.sample_rate)
            
            # Only consider positive frequencies
            freqs = freqs[:len(freqs)//2]
            fft_data = fft_data[:len(fft_data)//2]
            
            # Check for content in the target frequency range
            freq_mask = (freqs >= self.vad_min_freq) & (freqs <= self.vad_max_freq)
            
            # Get the frequency content in the target range
            target_range_content = fft_data[freq_mask]
            
            # Check if there is any content in the target frequency range
            has_content = len(target_range_content) > 0 and np.any(target_range_content > 0)
            
            # Update statistics
            self.total_chunks += 1
            if has_content:
                self.vad_active_chunks += 1
                logger.debug(f"VAD: Content detected in {self.vad_min_freq}-{self.vad_max_freq}Hz range")
            else:
                logger.debug(f"VAD: No content in {self.vad_min_freq}-{self.vad_max_freq}Hz range")
            
            # Log statistics periodically
            if self.total_chunks % 10 == 0:
                active_percentage = (self.vad_active_chunks / self.total_chunks) * 100 if self.total_chunks > 0 else 0
                logger.info(f"VAD stats: Active {self.vad_active_chunks}/{self.total_chunks} chunks ({active_percentage:.1f}%)")
            
            return has_content
                
        except Exception as e:
            logger.error(f"Error in VAD processing: {e}")
            return True  # Default to sending audio if VAD fails

    def process_window(self, window_data):
        """
        Process a single audio window.
        
        Args:
            window_data (numpy.ndarray): Audio data for one window (3 seconds)
        """
        try:
            # Apply Voice Activity Detection if enabled
            if not self.detect_voice_activity(window_data):
                logger.debug("No voice activity detected, skipping this window")
                return
            
            # Check if queue is full, remove oldest if necessary
            if self.chunk_queue.full():
                try:
                    # Remove oldest chunk
                    oldest_chunk = self.chunk_queue.get(block=False)
                    self.chunk_queue.task_done()
                    logger.warning("Queue full: Removed oldest audio chunk to make room for new one")
                except queue.Empty:
                    pass
            
            # Add new item to queue
            self.chunk_queue.put(window_data, block=False)
            chunk_id = f"audio_chunk_{self.save_counter}"
            
            # Send to WebSocket if connected
            if self.ws_connected:
                ws_send_thread = threading.Thread(
                    target=self.send_to_websocket,
                    args=(window_data, chunk_id)
                )
                ws_send_thread.daemon = True
                ws_send_thread.start()
            
            self.save_counter += 1
        except queue.Full:
            # Handle case where queue is still full after removal
            self.dropped_chunks_count += 1
            logger.warning(f"Queue still full after removal: Dropping audio chunk. Total dropped: {self.dropped_chunks_count}")
        except Exception as e:
            logger.error(f"Error processing audio window: {e}")

    def send_to_websocket(self, audio_data, chunk_id):
        """
        Send audio data through WebSocket connection.
        
        Args:
            audio_data (numpy.ndarray): Audio data to send (3 seconds)
            chunk_id (str): Identifier for this audio chunk
        """
        if not self.ws_connected:
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
                'timestamp': time.time(),
                'device_id': DEVICE_ID,
                'audio_data': encoded_data
            }
            
            # Send through WebSocket - directly send as JSON string
            if self.ws_client and self.ws_client.ws:
                self.ws_client.ws.send(json.dumps(payload))
                self.last_ws_status = "Data sent"
                logger.info(f"Audio sent via WebSocket: {chunk_id}")
            
        except Exception as e:
            logger.error(f"Error sending audio through WebSocket: {e}")
            self.last_ws_status = f"Send error: {str(e)}"

    def stop_recording(self):
        """
        Stop recording and clean up resources.
        """
        self.is_recording = False
        if self.stream:
            try:
                with self.suppress_alsa_errors():
                    self.stream.stop_stream()
                    self.stream.close()
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")
        
        # Close WebSocket
        self._stop_websocket()
        
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)
        
        logger.info("Audio recording stopped")

    def stop(self):
        """Stop the audio client"""
        self.running = False
        self.stop_recording()
        
    def close(self):
        """
        Close all resources and terminate PyAudio.
        """
        self.stop_recording()
        try:
            with self.suppress_alsa_errors():
                self.audio.terminate()
        except Exception as e:
            logger.error(f"Error terminating PyAudio: {e}")


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
