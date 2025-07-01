#!/usr/bin/env python3
"""
Import test script to verify all modules import correctly
"""

def test_imports():
    """Test all imports in the structured voice assistant"""
    
    print("Testing imports...")
    
    try:
        # Test config
        from config import Config
        print("✓ Config imported successfully")
        
        # Test utils
        from utils import safe_log, logger, convert_mulaw_to_wav, detect_speech_activity
        print("✓ Utils imported successfully")
        
        # Test models
        from models import CallSession, SessionManager, session_manager
        print("✓ Models imported successfully")
        
        # Test services
        from services import openai_service, sarvam_service, twilio_service, websocket_service
        print("✓ Services imported successfully")
        
        # Test individual service classes
        from services.openai_service import OpenAIService
        from services.sarvam_service import SarvamService
        from services.twilio_service import TwilioService
        from services.websocket_service import WebSocketService
        print("✓ Individual service classes imported successfully")
        
        # Test routes
        from routes import voice_bp, audio_bp, test_bp, websocket_bp, setup_websocket_routes
        print("✓ Routes imported successfully")
        
        # Test main app
        from app import create_app, start_periodic_cleanup, main
        print("✓ App functions imported successfully")
        
        # Test app creation
        app = create_app()
        print("✓ App created successfully")
        
        # Test configuration validation
        Config.validate_required_vars()
        print("✓ Configuration validation passed")
        
        print("\n🎉 All imports successful! The structured voice assistant is ready to run.")
        
    except Exception as e:
        print(f"❌ Import error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = test_imports()
    exit(0 if success else 1)