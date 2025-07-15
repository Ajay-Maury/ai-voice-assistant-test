import os
import uuid
import subprocess
import numpy as np
from openai import OpenAI
from config.settings import (
    AUDIO_CHUNK_DIR,
    AUDIO_SILENCE_THRESHOLDS,
    OPENAI_API_KEY,
    OPENAI_STT_MODEL,
)

import subprocess


# µ-law to PCM16 Decode Table (Standard G.711 Spec)
def _generate_mulaw_decode_table() -> np.ndarray:
    """
    Generates a lookup table that maps each of the 256 8-bit µ-law values
    to their corresponding 16-bit signed PCM linear values (as per ITU G.711).
    This avoids computing the µ-law formula at runtime.
    """
    MULAW_MAX = 0x1FFF  # Not directly used but part of G.711 constants
    BIAS = 0x84  # Bias for linear decoding (132)

    table = np.zeros(256, dtype=np.int16)

    for i in range(256):
        mu = ~i & 0xFF  # Invert 8-bit value (two's complement)
        sign = mu & 0x80  # Extract sign bit (bit 7)
        exponent = (mu >> 4) & 0x07  # Bits 4–6 (3-bit exponent)
        mantissa = mu & 0x0F  # Bits 0–3 (4-bit mantissa)

        # Decode using µ-law formula: ((mantissa << 4) + 0x08) << exponent
        sample = ((mantissa << 4) + 0x08) << exponent  # Reconstruct amplitude
        sample = sample - BIAS  # Remove bias

        if sign != 0:
            sample = -sample  # Apply sign (negative if sign bit is set)

        table[i] = sample  # Store in lookup table

    return table


# Precompute µ-law table (global, only once)
_mu_law_decode_table = _generate_mulaw_decode_table()


# µ-law Silence Detection Function
def is_mulaw_silent(
    mulaw_bytes: bytes,
    silence_threshold: int = AUDIO_SILENCE_THRESHOLDS["MAX_AMPLITUDE"],
    min_rms_db: float = AUDIO_SILENCE_THRESHOLDS["MIN_RMS_DBFS"],
) -> bool:
    """
    Detects whether a given chunk of 8-bit µ-law encoded audio is silent.
    Designed for real-time streams like Twilio's media payloads.

    Args:
        mulaw_bytes: Raw 8-bit µ-law encoded audio (base64-decoded from Twilio).
        silence_threshold: Max allowed sample amplitude before marking as "non-silent".
        min_rms_db: RMS (energy) threshold in dBFS below which audio is considered silent.

    Returns:
        True if the chunk is silent, False otherwise.
    """
    if not mulaw_bytes:
        return True  # Empty chunk is considered silent

    # Convert bytes to array of uint8 (0-255)
    mulaw = np.frombuffer(mulaw_bytes, dtype=np.uint8)

    # Decode using lookup table (vectorized for speed)
    pcm = _mu_law_decode_table[mulaw]  # -> 16-bit signed PCM

    # Step 1: Quick amplitude check — if any sample exceeds threshold, it's not silent
    if np.max(np.abs(pcm)) > silence_threshold:
        print(
            f"[DEBUG] Non-silent detected: max amplitude {np.max(np.abs(pcm))} exceeds threshold {silence_threshold}"
        )
        return False

    # Step 2: RMS energy calculation (Root Mean Square)
    pcm_float = pcm.astype(np.float32)  # Convert to float for RMS math
    rms = np.sqrt(np.mean(pcm_float**2))  # Square → mean → sqrt

    if rms == 0:
        return True  # Absolutely silent (flat zero)

    # Step 3: Convert RMS to dBFS (decibels relative to full-scale)
    # 32768.0 is the maximum amplitude in 16-bit PCM
    dbfs = 20 * np.log10(rms / 32768.0)

    # Step 4: Compare to minimum dBFS threshold
    if dbfs >= min_rms_db:
        print(
            f"[DEBUG] Non-silent detected: RMS: {rms}, dBFS: {dbfs}, Threshold: {min_rms_db}"
        )

    return dbfs < min_rms_db


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
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)

    return wav_path


def transcribe_audio_whisper(filepath):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        with open(filepath, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=OPENAI_STT_MODEL, 
                file=audio_file, 
                language="hi"
            )
        return result.text.strip() if result.text else ""
    except Exception as e:
        print("OpenAI Whisper error:", e)
        return ""


def transcribe_audio_azure(filepath, language="en-IN"):
    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_STT_SUBSCRIPTION_KEY, region=AZURE_STT_REGION
        )
        speech_config.speech_recognition_language = language

        audio_input = speechsdk.AudioConfig(filename=filepath)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_input
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
