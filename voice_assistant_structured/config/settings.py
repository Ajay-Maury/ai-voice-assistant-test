import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration settings"""
    
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
    PUBLIC_URL = os.getenv("PUBLIC_URL", "https://e04f-115-99-250-180.ngrok-free.app")
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    AZURE_OPENAI_VERSION = os.getenv("AZURE_OPENAI_VERSION", "2023-05-15")
    
    # Model Configuration
    WHISPER_MODEL = "whisper-1"
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
    
    # Sarvam AI TTS Configuration
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
    SARVAM_SPEAKER = os.getenv("SARVAM_SPEAKER", "manisha")
    SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "hi-IN")
    SARVAM_PITCH = float(os.getenv("SARVAM_PITCH", "0.0"))
    SARVAM_PACE = float(os.getenv("SARVAM_PACE", "1.0"))
    SARVAM_LOUDNESS = float(os.getenv("SARVAM_LOUDNESS", "1.0"))
    USE_SARVAM_TTS = os.getenv("USE_SARVAM_TTS", "false").lower() == "true"
    
    # Language Preference and Translation Configuration
    USER_LANGUAGE = os.getenv("USER_LANGUAGE", "kn-IN")
    AI_LANGUAGE = os.getenv("AI_LANGUAGE", "en-IN")
    USE_TRANSLATION = os.getenv("USE_TRANSLATION", "true").lower() == "true"
    
    # Speech Timing Configuration
    SPEECH_TIMEOUT = os.getenv("SPEECH_TIMEOUT", "2")
    WEBSOCKET_SPEECH_TIMEOUT = float(os.getenv("WEBSOCKET_SPEECH_TIMEOUT", "2.0"))
    WEBSOCKET_BUFFER_DURATION = float(os.getenv("WEBSOCKET_BUFFER_DURATION", "30.0"))
    
    # Server Configuration
    PORT = int(os.getenv("PORT", 8000))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # Session Configuration
    SESSION_TIMEOUT = 3600  # 1 hour
    CLEANUP_INTERVAL = 600  # 10 minutes
    
    @classmethod
    def validate_required_vars(cls):
        """Validate that required environment variables are set"""
        required_vars = [
            ("TWILIO_ACCOUNT_SID", cls.TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", cls.TWILIO_AUTH_TOKEN),
            ("TWILIO_PHONE_NUMBER", cls.TWILIO_NUMBER)
        ]
        
        for var_name, var_value in required_vars:
            if not var_value:
                raise ValueError(f"Missing required environment variable: {var_name}")
        
        # Validate OpenAI configuration
        if not cls.OPENAI_API_KEY and not all([cls.AZURE_OPENAI_API_KEY, cls.AZURE_OPENAI_ENDPOINT]):
            raise ValueError("Missing OpenAI configuration. Provide either OPENAI_API_KEY or Azure OpenAI credentials.")