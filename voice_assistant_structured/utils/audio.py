import io
import wave
import struct
import tempfile
import os
from .logger import safe_log

def convert_mulaw_to_wav(mulaw_data: bytes) -> bytes:
    """Convert μ-law audio data to WAV format for Whisper"""
    try:
        # Decode μ-law to 16-bit PCM
        pcm_data = []
        for byte in mulaw_data:
            # μ-law to linear PCM conversion
            byte = ~byte
            sign = byte & 0x80
            exponent = (byte >> 4) & 0x07
            mantissa = byte & 0x0F
            
            sample = mantissa << (exponent + 3)
            if exponent > 0:
                sample += (1 << (exponent + 7))
            if sign:
                sample = -sample
            
            pcm_data.append(sample)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(8000)  # 8kHz sample rate
            
            # Pack PCM data as 16-bit signed integers
            wav_data = struct.pack('<' + 'h' * len(pcm_data), *pcm_data)
            wav_file.writeframes(wav_data)
        
        wav_buffer.seek(0)
        return wav_buffer.getvalue()
        
    except Exception as e:
        safe_log('error', f"Audio conversion error: {str(e)}")
        return b''

def detect_speech_activity(audio_data: bytes) -> bool:
    """Simple speech activity detection based on audio amplitude"""
    try:
        # Convert audio data to amplitude values
        if len(audio_data) == 0:
            return False
        
        # Calculate RMS (Root Mean Square) for amplitude
        rms = 0
        for i in range(0, len(audio_data), 2):
            if i + 1 < len(audio_data):
                sample = int.from_bytes(audio_data[i:i+2], byteorder='little', signed=True)
                rms += sample * sample
        
        rms = (rms / (len(audio_data) // 2)) ** 0.5
        
        # Threshold for speech detection (adjust as needed)
        speech_threshold = 500  # Empirical value
        return rms > speech_threshold
        
    except Exception as e:
        safe_log('error', f"Speech detection error: {str(e)}")
        return False