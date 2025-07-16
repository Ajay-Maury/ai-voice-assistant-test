import os
from dotenv import load_dotenv

load_dotenv()

AI_SYSTEM_PROMPT = "You are a friendly, conversational human assistant. Respond naturally and warmly, as if you are speaking to a friend. Keep responses concise and conversational, suitable for voice interaction. Limit responses to 1-2 sentences."

AUDIO_CHUNK_DIR = "audio_chunks"
os.makedirs(AUDIO_CHUNK_DIR, exist_ok=True)

RESPONSE_AUDIO_CHUNK_DIR = "response_audio_chunks"
os.makedirs(RESPONSE_AUDIO_CHUNK_DIR, exist_ok=True)

AUDIO_SILENCE_THRESHOLDS = {
    "MAX_AMPLITUDE": 1000,  # If any sample exceeds this, it's not silent
    "MIN_RMS_DBFS": -40.0,  # If average energy (RMS in dBFS) is above this, it's not silent
}

AUDIO_CHUNK_SIZE = 160  # Size of audio chunks in bytes (20ms at 8000Hz) 
AUDIO_SAMPLE_RATE = 8000  # Sample rate for audio
SILENCE_MAX_DURATION=0.8  # Max seconds of silence to be added in audio buffer  s
AUDIO_BUFFER_SILENCE = 1.5  # Seconds of silence to wait before processing audio
MIN_AUDIO_BYTES = 1000  # ≈ 0.125 seconds of μ-law audio at 8kHz

ENGAGEMENT_RESPONSES = {
    "ENGAGED": {
        "en": ["hmm", "okay", "got it", "yeah"],
        "hi": ["हां", "अच्छा", "ओके", "ठीक है"]
        # Add more languages here
    },
    "DISENGAGED": {
        "en": ["Are you there?", "Still with me?", "Can you hear me?"],
        "hi": ["क्या आप अभी भी लाइन पर हैं?", "क्या मेरी बात सुन पा रहे हैं?", "आपकी आवाज़ नहीं आ रही है!",],
        # Add more languages here
    }
}

ENGAGEMENT_TRIGGER_SECONDS = 3.0                         # seconds of continuous speech
ENGAGEMENT_BACKCHANNEL_REPEAT_DELAY = 3.0                # repeat interval for engagement task
DISENGAGEMENT_TRIGGER_SECONDS = 10.0                     # seconds of silence
DISENGAGEMENT_BACKCHANNEL_REPEAT_DELAY = 5.0             # repeat interval for disengagement task

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = str(os.getenv("TWILIO_PHONE_NUMBER"))
VERIFIED_TEST_NUMBER = os.getenv("VERIFIED_TEST_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "whisper-1")

WHISPER_STT_OFFLINE_MODEL = os.getenv("WHISPER_STT_OFFLINE_MODEL", "medium")    # "medium" for better accuracy

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_CHAT_TEMPERATURE = float(os.getenv("GROQ_CHAT_TEMPERATURE", 0.1))

REDIS_URL = os.getenv("REDIS_URL")
WEB_SOCKET_URL = os.getenv("WEBSOCKET_URL")
VOICE_ROUTE_URL = os.getenv("VOICE_ROUTE_URL")

SARVAM_SUBSCRIPTION_KEY=os.getenv("SARVAM_SUBSCRIPTION_KEY")
SARVAM_VOICE=os.getenv("SARVAM_VOICE", "anushka")
SARVAM_LANGUAGE=os.getenv("SARVAM_LANGUAGE", "hi-IN")
SARVAM_TTS_MODEL=os.getenv("SARVAM_TTS_MODEL", "bulbul:v2")
SARVAM_STT_MODEL=os.getenv("SARVAM_STT_MODEL","saarika:v2.5")