import os
import azure.cognitiveservices.speech as speechsdk

AZURE_KEY = os.getenv("AZURE_TTS_KEY")
AZURE_REGION = os.getenv("AZURE_TTS_REGION")
VOICE = "en-US-JennyNeural"

def synthesize_azure_tts_to_pcm(text):

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
    speech_config.speech_synthesis_voice_name = VOICE
    
    # Use raw audio output format
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw8Khz8BitMonoMULaw
    )
    
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data  # This is raw μ-law audio
    else:
        print(f"[ERROR] TTS failed: {result.reason}")
        return None