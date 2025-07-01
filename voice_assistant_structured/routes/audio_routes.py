import os
import threading
from flask import Blueprint, send_file
from utils.logger import safe_log
from services import sarvam_service

audio_bp = Blueprint('audio', __name__)

@audio_bp.route('/audio/<audio_id>')
def serve_audio(audio_id):
    """Serve generated audio files"""
    try:
        filepath = sarvam_service.get_audio_file_path(audio_id)
        if filepath and os.path.exists(filepath):
            def cleanup_after_send():
                # Clean up after serving
                try:
                    sarvam_service.cleanup_audio(audio_id)
                except:
                    pass
            
            # Schedule cleanup after response
            threading.Timer(5.0, cleanup_after_send).start()
            
            # Determine mimetype based on file extension
            if filepath.endswith('.wav'):
                mimetype = 'audio/wav'
            elif filepath.endswith('.mp3'):
                mimetype = 'audio/mpeg'
            else:
                mimetype = 'audio/wav'  # Default to WAV for Sarvam AI
            
            return send_file(filepath, mimetype=mimetype)
        
        return "Audio not found", 404
    except Exception as e:
        safe_log('error', f"Audio serving error: {str(e)}")
        return "Error serving audio", 500