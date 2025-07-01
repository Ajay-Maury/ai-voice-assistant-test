from flask import Blueprint
from utils.logger import safe_log
from services import websocket_service

websocket_bp = Blueprint('websocket', __name__)

def setup_websocket_routes(sockets):
    """Setup WebSocket routes if flask-sockets is available"""
    if not sockets:
        # Fallback: Create a dummy endpoint if WebSocket is not available
        @websocket_bp.route('/stream', methods=['GET', 'POST'])
        def stream_fallback():
            safe_log('warning', "WebSocket stream requested but flask-sockets not available")
            return "WebSocket streaming not available", 501
        return
    
    @sockets.route('/stream')
    def media_stream(ws):
        """Handle WebSocket media stream from Twilio"""
        sid = None
        
        # Initialize stream state with thread-safe access
        stream_key = id(ws)  # Use websocket ID as temporary key
        websocket_service.initialize_stream_state(stream_key, ws)
        
        try:
            while not ws.closed:
                msg = ws.receive()
                if not msg:
                    break
                
                # Handle the message and get SID if it's a start event
                result = websocket_service.handle_websocket_message(ws, msg, stream_key)
                if result:  # This would be the SID from a start event
                    sid = result
                    
        except Exception as e:
            safe_log('error', f"WebSocket error: {str(e)}")
        finally:
            # Clean up stream state
            cleanup_keys = [k for k in [stream_key, sid] if k]
            websocket_service.cleanup_stream_state(*cleanup_keys)
            
            if not ws.closed:
                try:
                    ws.close()
                except:
                    pass