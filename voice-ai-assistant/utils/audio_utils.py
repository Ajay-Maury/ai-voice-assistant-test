import os
import uuid
import wave
import whisper
import subprocess
import numpy as np

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()


AZURE_SPEECH_KEY = os.getenv("AZURE_STT_SUBSCRIPTION_KEY")
AZURE_SERVICE_REGION = os.getenv("AZURE_STT_REGION")

# You can define a list of possible languages
POSSIBLE_LANGUAGES = ["en-IN", "en-US", "hi-IN", "ta-IN", "te-IN"]

# Silence detector
def is_silent(pcm_data, threshold=100):
    if len(pcm_data) < 2:
        return True  # Not enough data to be meaningful

    pcm_array = np.frombuffer(pcm_data, dtype=np.int16)

    if pcm_array.size == 0:
        return True  # Definitely silent

    mean_square = np.mean(np.square(pcm_array.astype(np.float32)))
    if np.isnan(mean_square) or mean_square <= 0:
        return True  # Invalid or no signal

    rms = np.sqrt(mean_square)
    print(f"[Silence Check]: RMS={rms:.2f}")
    return rms < threshold

AUDIO_DIR = "audio_chunks"
os.makedirs(AUDIO_DIR, exist_ok=True)

def save_audio_chunk(call_sid, audio_bytes):
    raw_path = os.path.join(AUDIO_DIR, f"{call_sid}_{uuid.uuid4()}.raw")
    wav_path = raw_path.replace(".raw", ".wav")

    # Save raw μ-law audio (as received from Twilio)
    with open(raw_path, "wb") as f:
        f.write(audio_bytes)

    # Convert μ-law to 16-bit PCM WAV using ffmpeg
    try:
        subprocess.run([
            "ffmpeg",
            "-f", "mulaw",
            "-ar", "8000",
            "-ac", "1",
            "-i", raw_path,
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            wav_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[ERROR] Failed to convert audio: {e}")
        return None
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)

    return wav_path

def transcribe_audio(filepath):
    try:
        model = whisper.load_model("medium")
        result = model.transcribe(filepath, language="en")
        return " ".join(result["text"]).strip() if isinstance(result["text"], list) else result["text"].strip()
    except Exception as e:
        print("Whisper error:", e)
        return ""

def transcribe_audio_azure(filepath, language="en-US"):
    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_SERVICE_REGION
        )
        speech_config.speech_recognition_language = language

        audio_input = speechsdk.AudioConfig(filename=filepath)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_input
        )

        print(f"[Azure STT]: Transcribing {filepath}...")
        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print(f"[Azure STT]: Recognized: {result.text}")
            return result.text
        else:
            print(f"[Azure STT]: No recognition, Reason: {result.reason}")
            return ""
    except Exception as e:
        print(f"[Azure STT Error]: {e}")
        return ""