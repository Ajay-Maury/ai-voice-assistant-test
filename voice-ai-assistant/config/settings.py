import os
from dotenv import load_dotenv

load_dotenv()

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = str(os.getenv("TWILIO_PHONE_NUMBER"))

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_ENDPOINT = str(os.getenv("AZURE_OPENAI_ENDPOINT"))
AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-35-turbo")

AZURE_TTS_KEY = os.getenv("AZURE_TTS_KEY")
AZURE_TTS_REGION = os.getenv("AZURE_TTS_REGION")
AZURE_TTS_VOICE = "en-US-JennyNeural"

AZURE_STT_SUBSCRIPTION_KEY = os.getenv("AZURE_STT_SUBSCRIPTION_KEY")
AZURE_STT_REGION = os.getenv("AZURE_STT_REGION")

REDIS_URL = os.getenv("REDIS_URL")
WEB_SOCKET_URL = os.getenv("WEBSOCKET_URL")
VOICE_ROUTE_URL = os.getenv("VOICE_ROUTE_URL")

AI_SYSTEM_PROMPT = "You are a friendly, conversational human assistant. Respond naturally and warmly, as if you are speaking to a friend. Keep responses concise and conversational, suitable for voice interaction. Limit responses to 1-2 sentences."

AUDIO_CHUNK_DIR = "audio_chunks"
os.makedirs(AUDIO_CHUNK_DIR, exist_ok=True)

RESPONSE_AUDIO_CHUNK_DIR = "response_audio_chunks"
os.makedirs(RESPONSE_AUDIO_CHUNK_DIR, exist_ok=True)

AUDIO_RMS_THRESHOLD = 150.0  # RMS threshold for silence detection
AUDIO_CHUNK_SIZE = 160  # Size of audio chunks in bytes (20ms at 8000Hz)
AUDIO_SAMPLE_RATE = 8000  # Sample rate for audio

AUDIO_BUFFER_SILENCE = 2  # Seconds of silence to wait before processing audio
MIN_AUDIO_BYTES = 1000  # ≈ 0.125 seconds of μ-law audio at 8kHz

