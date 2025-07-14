import os
import hashlib
import aiohttp
import asyncio
import subprocess

from dotenv import load_dotenv

load_dotenv()


ENGAGEMENT_AUDIO_DIR = "static/engagement_audios"
os.makedirs(ENGAGEMENT_AUDIO_DIR, exist_ok=True)

async def get_engagement_audio(text: str) -> str:
    filename = hashlib.md5(text.encode()).hexdigest()
    print(f"[ENGAGE] Fetching audio for: {text} (filename: {filename})")
    mulaw_path = os.path.join(ENGAGEMENT_AUDIO_DIR, f"{filename}.mulaw")
    pcm_path = os.path.join(ENGAGEMENT_AUDIO_DIR, f"{filename}.pcm")

    if os.path.exists(mulaw_path):
        print(f"[ENGAGE][CACHE HIT] {text}")
        return mulaw_path

    print(f"[ENGAGE][CACHE MISS] Generating audio for: {text}")

    # Call OpenAI TTS API
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2"
    }
    payload = {
        "model": OPENAI_TTS_MODEL,
        "voice": OPENAI_TTS_VOICE,
        "input": text,
        "response_format": "pcm"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                raise Exception(f"TTS failed: {await resp.text()}")
            with open(pcm_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024):
                    f.write(chunk)

    # Convert PCM (24kHz) → μ-law (8kHz mono) using ffmpeg
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", pcm_path,
            "-ar", "8000", "-ac", "1", "-f", "mulaw",
            mulaw_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[ENGAGE][CACHE SAVE] {mulaw_path}")
    except subprocess.CalledProcessError as e:
        raise Exception(f"FFmpeg conversion failed: {e}")
    finally:
        if os.path.exists(pcm_path):
            os.remove(pcm_path)

    return mulaw_path


TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = str(os.getenv("TWILIO_PHONE_NUMBER"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "whisper-1")

REDIS_URL = os.getenv("REDIS_URL")
WEB_SOCKET_URL = os.getenv("WEBSOCKET_URL")
VOICE_ROUTE_URL = os.getenv("VOICE_ROUTE_URL")

AI_SYSTEM_PROMPT = "You are a friendly, conversational human assistant. Respond naturally and warmly, as if you are speaking to a friend. Keep responses concise and conversational, suitable for voice interaction. Limit responses to 1-2 sentences."

AUDIO_CHUNK_DIR = "audio_chunks"
os.makedirs(AUDIO_CHUNK_DIR, exist_ok=True)

RESPONSE_AUDIO_CHUNK_DIR = "response_audio_chunks"
os.makedirs(RESPONSE_AUDIO_CHUNK_DIR, exist_ok=True)

AUDIO_SILENCE_THRESHOLDS = {
    "MAX_AMPLITUDE": 1000,  # If any sample exceeds this, it's not silent
    "MIN_RMS_DBFS": -40.0,  # If average energy (RMS in dBFS) is above this, it's not silent
}

AUDIO_RMS_THRESHOLD = 150.0  # RMS threshold for silence detection
AUDIO_CHUNK_SIZE = 160  # Size of audio chunks in bytes (20ms at 8000Hz)
AUDIO_SAMPLE_RATE = 8000  # Sample rate for audio

AUDIO_BUFFER_SILENCE = 2  # Seconds of silence to wait before processing audio
MIN_AUDIO_BYTES = 1000  # ≈ 0.125 seconds of μ-law audio at 8kHz

ENGAGEMENT_RESPONSES = {
    "ENGAGED": ["hmm", "okay", "got it", "yeah"],
    "DISENGAGED": ["Are you there?", "Still with me?", "Can you hear me?"],
}
