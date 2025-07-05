import os
import uuid
import subprocess
import numpy as np
from openai import OpenAI
from config.settings import (
    AUDIO_CHUNK_DIR,
    AUDIO_RMS_THRESHOLD,
    OPENAI_API_KEY,
    OPENAI_STT_MODEL,
)


# Silence detector
def silent_detected(pcm_data, threshold=AUDIO_RMS_THRESHOLD):
    if len(pcm_data) < 2:
        return True
    pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
    if pcm_array.size == 0:
        return True
    rms = np.sqrt(np.mean(np.square(pcm_array))) or 0.0
    if not rms < threshold:
        print(f"[DEBUG] RMS: {rms}, Threshold: {threshold}")
    return rms < threshold


def save_audio_chunk(call_sid, audio_bytes):
    raw_path = os.path.join(AUDIO_CHUNK_DIR, f"{call_sid}_{uuid.uuid4()}.raw")
    wav_path = raw_path.replace(".raw", ".wav")

    # Save raw μ-law audio (as received from Twilio)
    with open(raw_path, "wb") as f:
        f.write(audio_bytes)

    # Convert μ-law to 16-bit PCM WAV using ffmpeg
    try:
        subprocess.run([
            "ffmpeg",
            "-f", "mulaw",         # input format
            "-ar", "8000",         # input sample rate
            "-ac", "1",            # input channels
            "-i", raw_path,        # input file
            "-ar", "16000",        # output sample rate (for ASR)
            "-ac", "1",            # mono
            "-c:a", "pcm_s16le",   # force 16-bit PCM
            # "-f", "wav",           # Output format is WAV
            wav_path               # output file
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # Suppress output and raise error if conversion fails

    except Exception as e:
        print(f"[ERROR] Failed to convert audio: {e}")
        return None
    # finally:
    #     if os.path.exists(raw_path):
    #         os.remove(raw_path)

    return wav_path


def transcribe_audio_whisper(filepath):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        with open(filepath, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=OPENAI_STT_MODEL,
                file=audio_file,
                language="en"
            )
        return result.text.strip() if result.text else ""
    except Exception as e:
        print("OpenAI Whisper error:", e)
        return ""


def transcribe_audio_azure(filepath, language="en-IN"):
    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_STT_SUBSCRIPTION_KEY,
            region=AZURE_STT_REGION
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