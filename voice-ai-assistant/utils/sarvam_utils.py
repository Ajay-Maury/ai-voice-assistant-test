import base64
import os
import subprocess
import uuid
from sarvamai import SarvamAI
from sarvamai.play import save

from config.settings import RESPONSE_AUDIO_CHUNK_DIR, SARVAM_SUBSCRIPTION_KEY, SARVAM_VOICE, SARVAM_LANGUAGE, SARVAM_MODEL

client = SarvamAI(api_subscription_key=SARVAM_SUBSCRIPTION_KEY)


async def synthesize_mulaw_sarvam_tts(text: str, voice: str = SARVAM_VOICE, lang: str = SARVAM_LANGUAGE):
    try:
        audio_response = client.text_to_speech.convert(
            text=text,
            model=SARVAM_MODEL,    # type: ignore
            target_language_code=lang,
            speech_sample_rate=8000,
            speaker=voice,
        )

        if not audio_response or not hasattr(audio_response, "audios") or not audio_response.audios:
            print("[Sarvam TTS]: No audio content received.")
            return b""

        # Decode the first audio chunk (base64)
        wav_bytes = base64.b64decode(audio_response.audios[0])

        # Save WAV
        wav_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"sarvam_tts_{uuid.uuid4()}.wav")
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        # Convert to μ-law
        mulaw_path = wav_path.replace(".wav", ".raw")

        subprocess.run([
            "ffmpeg", "-i", wav_path,
            "-ar", "8000", "-ac", "1",
            "-acodec", "pcm_mulaw", "-f", "mulaw", "-y", mulaw_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with open(mulaw_path, "rb") as f:
            audio_data = f.read()

        # Remove audio  files
        os.remove(wav_path)
        os.remove(mulaw_path)

        return audio_data

    except subprocess.CalledProcessError as ffmpeg_err:
        print(f"[Sarvam TTS]: FFmpeg conversion failed: {ffmpeg_err}")
        return b""

    except Exception as e:
        print(f"[Sarvam TTS]: Error generating TTS audio: {e}")
        return b""


def detect_text_language(text):
    response = client.text.identify_language(
        input=text
    )
    return response.language_code

def transcribe_audio_sarvam(filepath):
    response = client.speech_to_text.transcribe(
        file=open(filepath, "rb"),
        model="saarika:v2.5",
        language_code="hi-IN"
    )
    # print(f"sarvam stt response--: {response.transcript}")
    return response.transcript
