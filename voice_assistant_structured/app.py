import threading
import time
from flask import Flask
try:
    from flask_sockets import Sockets
    FLASK_SOCKETS_AVAILABLE = True
except ImportError:
    FLASK_SOCKETS_AVAILABLE = False

from config import Config
from utils.logger import safe_log
from models.session import session_manager
from routes import voice_bp, audio_bp, test_bp, websocket_bp, setup_websocket_routes

def create_app():
    """Application factory function"""
    # Validate configuration
    Config.validate_required_vars()
    
    app = Flask(__name__)
    
    # Initialize sockets only if flask-sockets is available
    sockets = None
    if FLASK_SOCKETS_AVAILABLE:
        sockets = Sockets(app)
        safe_log('info', "Flask-Sockets initialized")
    else:
        safe_log('warning', "Flask-Sockets not available, WebSocket features disabled")
    
    # Register blueprints
    app.register_blueprint(voice_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(test_bp)
    app.register_blueprint(websocket_bp)
    
    # Setup WebSocket routes
    setup_websocket_routes(sockets)
    
    # Add error handling for WebSocket routing
    @app.errorhandler(Exception)
    def handle_websocket_error(e):
        if "WebsocketMismatch" in str(e):
            safe_log('warning', f"WebSocket connection mismatch: {str(e)}")
            return "WebSocket connection not supported", 400
        return str(e), 500
    
    return app

def start_periodic_cleanup():
    """Start a background thread to periodically clean up old sessions"""
    def cleanup_task():
        while True:
            try:
                time.sleep(Config.CLEANUP_INTERVAL)
                session_manager.cleanup_expired_sessions()
            except Exception as e:
                safe_log('error', f"Periodic cleanup error: {str(e)}")
    
    cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
    cleanup_thread.start()
    safe_log('info', "Started periodic session cleanup thread")

def main():
    """Main application entry point"""
    app = create_app()
    
    # Start periodic cleanup
    start_periodic_cleanup()
    
    if Config.DEBUG:
        # Development server
        safe_log('info', f"Starting development server on port {Config.PORT}")
        app.run(host="0.0.0.0", port=Config.PORT, debug=True)
    else:
        # Production server with gevent
        from gevent import pywsgi
        from geventwebsocket.handler import WebSocketHandler
        
        safe_log('info', f"Starting voice assistant server on port {Config.PORT} with conversation memory")
        server = pywsgi.WSGIServer(("0.0.0.0", Config.PORT), app, handler_class=WebSocketHandler)
        server.serve_forever()

if __name__ == "__main__":
    main()