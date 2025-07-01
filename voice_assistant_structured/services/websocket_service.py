import json
import base64
import time
import io
import tempfile
from typing import Dict
from config import Config
from utils.logger import safe_log
from utils.audio import convert_mulaw_to_wav
from .openai_service import openai_service

class WebSocketService:
    """Service for handling WebSocket media streams"""
    
    def __init__(self):
        self.stream_state: Dict = {}
    
    def should_process_speech_buffer(self, sid: str) -> bool:
        """Determine if we should process the accumulated speech buffer"""
        if sid not in self.stream_state:
            return False
        
        state = self.stream_state[sid]
        current_time = time.time()
        
        # Check if we have enough silence after speech
        if (state.get('silence_start_time') and 
            current_time - state['silence_start_time'] >= Config.WEBSOCKET_SPEECH_TIMEOUT):
            return True
        
        # Check if buffer is getting too long
        if (state.get('speech_start_time') and 
            current_time - state['speech_start_time'] >= Config.WEBSOCKET_BUFFER_DURATION):
            return True
        
        return False
    
    def transcribe_audio_buffer(self, audio_buffer: io.BytesIO) -> str:
        """Transcribe audio buffer using Whisper"""
        try:
            audio_buffer.seek(0)
            raw_audio = audio_buffer.getvalue()
            
            if len(raw_audio) < 1000:  # Skip very short audio clips
                return ""
            
            # Convert μ-law to WAV format
            wav_data = convert_mulaw_to_wav(raw_audio)
            if not wav_data:
                return ""
            
            # Create a temporary WAV file for Whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(wav_data)
                tmp_file.flush()
                
                # Transcribe using OpenAI service
                transcript = openai_service.transcribe_audio(tmp_file.name)
                
                # Clean up temporary file
                import os
                os.unlink(tmp_file.name)
                
                return transcript
                
        except Exception as e:
            safe_log('error', f"Audio transcription error: {str(e)}")
            return ""
    
    def handle_websocket_message(self, ws, msg: str, stream_key):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(msg)
        except json.JSONDecodeError as e:
            safe_log('error', f"Invalid JSON received: {str(e)}")
            return
            
        event = data.get('event')
        
        if event == 'start':
            sid = data.get('streamSid')
            if sid:
                # Move state to proper SID key
                if stream_key in self.stream_state:
                    self.stream_state[sid] = self.stream_state.pop(stream_key)
                    self.stream_state[sid].update({
                        'ws': ws,
                        'bot_talking': True,
                        'last_activity': time.time()
                    })
                safe_log('info', f"Stream started with SID: {sid}")
                return sid
                
        elif event == 'media':
            sid = data.get('streamSid')
            if sid and sid in self.stream_state:
                payload = data.get('media', {}).get('payload', '')
                if payload:
                    try:
                        audio_data = base64.b64decode(payload)
                        if 'buffer' in self.stream_state[sid]:
                            self.stream_state[sid]['buffer'].write(audio_data)
                        self.stream_state[sid]['last_activity'] = time.time()
                    except Exception as e:
                        safe_log('error', f"Error processing audio data: {str(e)}")
                        
        elif event == 'stop':
            sid = data.get('streamSid')
            if sid and sid in self.stream_state:
                buffer = self.stream_state[sid].get('buffer')
                if buffer and buffer.tell() > 0:  # Only process if there's audio data
                    transcript = self.transcribe_audio_buffer(buffer)
                    if transcript:
                        safe_log('info', f"Whisper transcript: {transcript}")
                        # Store transcript for potential use
                        self.stream_state[sid]['last_transcript'] = transcript
        
        return None
    
    def initialize_stream_state(self, stream_key, ws):
        """Initialize stream state for a new WebSocket connection"""
        self.stream_state[stream_key] = {
            'ws': ws, 
            'buffer': io.BytesIO(), 
            'bot_talking': True,
            'last_activity': time.time(),
            'speech_start_time': None,
            'silence_start_time': None,
            'is_speaking': False
        }
    
    def cleanup_stream_state(self, *keys):
        """Clean up stream state for given keys"""
        for key in keys:
            if key and key in self.stream_state:
                self.stream_state.pop(key, None)

# Global WebSocket service instance
websocket_service = WebSocketService()