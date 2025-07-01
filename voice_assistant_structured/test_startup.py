#!/usr/bin/env python3
"""
Test script to verify the application can start properly
"""

import signal
import sys
import threading
import time

def test_startup():
    """Test that the application can start and initialize properly"""
    
    print("Testing application startup...")
    
    try:
        from app import create_app, start_periodic_cleanup
        from config import Config
        
        # Create the app
        app = create_app()
        print("✓ Flask app created successfully")
        
        # Start periodic cleanup in test mode
        start_periodic_cleanup()
        print("✓ Periodic cleanup thread started")
        
        # Test that we can get the test client
        with app.test_client() as client:
            print("✓ Test client created successfully")
        
        print(f"✓ Server would start on port {Config.PORT}")
        print(f"✓ Debug mode: {Config.DEBUG}")
        
        print("\n🎉 Application startup test successful!")
        print("The structured voice assistant is ready to run with:")
        print(f"  python app.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Startup error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_startup()
    exit(0 if success else 1)