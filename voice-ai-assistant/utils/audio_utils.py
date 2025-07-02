import os
import uuid
import wave
import whisper
import subprocess
model = whisper.load_model("base")

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
        result = model.transcribe(filepath)
        return " ".join(result["text"]).strip() if isinstance(result["text"], list) else result["text"].strip()
    except Exception as e:
        print("Whisper error:", e)
        return ""
