import os
import uuid
import azure.cognitiveservices.speech as speechsdk
from config.settings import (
    AZURE_TTS_KEY,
    AZURE_TTS_REGION,
    AZURE_TTS_VOICE,
    RESPONSE_AUDIO_CHUNK_DIR,
)

def synthesize_azure_tts_to_pcm(text):

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_TTS_KEY, region=AZURE_TTS_REGION)
    speech_config.speech_synthesis_voice_name = AZURE_TTS_VOICE
    
    # Use raw audio output format
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw8Khz8BitMonoMULaw
    )
    
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result is not None and hasattr(result, "reason") and result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        raw_path = os.path.join(RESPONSE_AUDIO_CHUNK_DIR, f"_{uuid.uuid4()}.raw")
        # Save raw μ-law audio (as received from tts)
        with open(raw_path, "wb") as f:
            f.write(result.audio_data)
        return result.audio_data  # This is raw μ-law audio
    else:
        error_reason = getattr(result, "reason", "Unknown error")
        print(f"[ERROR] TTS failed: {error_reason}")
        return None