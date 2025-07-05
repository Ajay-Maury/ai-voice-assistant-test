import os
import uuid
import subprocess
from openai import OpenAI
from config.settings import (
    OPENAI_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    RESPONSE_AUDIO_CHUNK_DIR,
)

def synthesize_openai_tts_to_pcm(text):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Generate speech using OpenAI TTS with higher quality
        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="wav",  # Better quality than MP3
            speed=1.0
        )
        
        # Save the WAV response
        wav_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"tts_{uuid.uuid4()}.wav")
        with open(wav_path, "wb") as f:
            f.write(response.content)
        
        # Convert WAV to μ-law PCM format (8kHz, 8-bit, mono, μ-law)
        raw_path = wav_path.replace(".wav", ".raw")
        
        try:
            subprocess.run([
                "ffmpeg",
                "-i", wav_path,           # input WAV file
                "-ar", "8000",            # output sample rate (8kHz for Twilio)
                "-ac", "1",               # mono
                "-acodec", "pcm_mulaw",   # explicit μ-law codec
                "-f", "mulaw",            # output format μ-law
                "-y",                     # overwrite output
                raw_path                  # output file
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Read the converted μ-law data
            with open(raw_path, "rb") as f:
                audio_data = f.read()
            
            # Clean up temporary files
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(raw_path):
                os.remove(raw_path)
                
            return audio_data
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] FFmpeg conversion failed: {e}")
            return None
            
    except Exception as e:
        print(f"[ERROR] OpenAI TTS failed: {e}")
        return None