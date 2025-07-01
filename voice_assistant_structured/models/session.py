import time
import uuid
import threading
from typing import Dict, List, Optional
from utils.logger import safe_log
from config import Config

class CallSession:
    """Represents a single call session with conversation memory"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.conversation_history: List[Dict] = []
        self.start_time = time.time()
        self.last_activity = time.time()
        self._lock = threading.Lock()
    
    def add_message(self, role: str, content: str):
        """Add a message to the conversation history"""
        with self._lock:
            self.conversation_history.append({
                'role': role,
                'content': content,
                'timestamp': time.time()
            })
            self.last_activity = time.time()
    
    def get_conversation_context(self) -> List[Dict]:
        """Get conversation history formatted for OpenAI messages"""
        with self._lock:
            return [{'role': msg['role'], 'content': msg['content']} 
                   for msg in self.conversation_history]
    
    def is_expired(self) -> bool:
        """Check if session has expired"""
        return time.time() - self.last_activity > Config.SESSION_TIMEOUT

class SessionManager:
    """Manages call sessions and conversation memory"""
    
    def __init__(self):
        self._sessions: Dict[str, CallSession] = {}
        self._lock = threading.Lock()
    
    def get_session_id_from_request(self, request_form) -> str:
        """Extract or generate a unique call session ID from Twilio request"""
        call_sid = request_form.get('CallSid')
        if call_sid:
            return call_sid
        
        # Fallback: generate a temporary session ID
        return f"session_{str(uuid.uuid4())[:8]}"
    
    def init_session(self, session_id: str) -> CallSession:
        """Initialize a new call session or return existing one"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = CallSession(session_id)
                safe_log('info', f"Initialized call session: {session_id}")
            return self._sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[CallSession]:
        """Get an existing session"""
        with self._lock:
            return self._sessions.get(session_id)
    
    def add_to_conversation(self, session_id: str, role: str, content: str):
        """Add a message to the conversation history"""
        session = self.get_session(session_id)
        if session:
            session.add_message(role, content)
            safe_log('info', f"Added to conversation history ({session_id}): {role} - {content[:50]}...")
    
    def get_conversation_context(self, session_id: str) -> List[Dict]:
        """Get conversation history formatted for OpenAI messages"""
        session = self.get_session(session_id)
        return session.get_conversation_context() if session else []
    
    def cleanup_expired_sessions(self):
        """Clean up expired conversation sessions"""
        try:
            with self._lock:
                expired_sessions = [
                    session_id for session_id, session in self._sessions.items()
                    if session.is_expired()
                ]
                
                for session_id in expired_sessions:
                    self._sessions.pop(session_id, None)
                    safe_log('info', f"Cleaned up expired session: {session_id}")
                    
        except Exception as e:
            safe_log('error', f"Session cleanup error: {str(e)}")
    
    def get_active_sessions_info(self) -> Dict:
        """Get information about active sessions for debugging"""
        with self._lock:
            sessions_info = {}
            for session_id, session in self._sessions.items():
                sessions_info[session_id] = {
                    'start_time': session.start_time,
                    'last_activity': session.last_activity,
                    'conversation_count': len(session.conversation_history),
                    'conversation_history': session.conversation_history[-5:]  # Last 5 messages
                }
            
            return {
                'active_sessions': len(self._sessions),
                'sessions': sessions_info,
                'memory_info': f"Tracking {len(self._sessions)} active conversations"
            }

# Global session manager instance
session_manager = SessionManager()