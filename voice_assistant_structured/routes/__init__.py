from .voice_routes import voice_bp
from .audio_routes import audio_bp
from .test_routes import test_bp
from .websocket_routes import websocket_bp, setup_websocket_routes

__all__ = ['voice_bp', 'audio_bp', 'test_bp', 'websocket_bp', 'setup_websocket_routes']